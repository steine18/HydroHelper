"""
ALERT2 IND Packet Decoder

Decodes:
  1. MANT payload (application PDU) as a hex string — colon, space, or dash separated.
  2. IND CSV format output lines (starting with AL22a).

Protocol references:
  - ALERT2 IND API Specification v2.0 (June 2020)
  - A Description of the ALERT2 Protocol (Don Van Wie, October 2011)
"""

import re
import struct

# ---------------------------------------------------------------------------
# Lookup tables
# ---------------------------------------------------------------------------

SENSOR_NAMES = {
    0: 'Reserved',
    1: 'Rain',
    2: 'Stage',
    3: 'Battery',
    4: 'Wind Speed',
    5: 'Wind Direction',
    6: 'Peak Wind Speed',
    7: 'Air Temperature',
    8: 'Relative Humidity',
    9: 'Air Pressure',
    10: 'Status',
    11: 'Flow Velocity',
    255: 'Timestamp',
}

SENSOR_UNITS = {
    1: 'tips',
    2: 'ft',
    3: 'V',
    4: 'mph',
    5: 'deg',
    6: 'mph',
    7: '°F',
    8: '%',
    9: 'mBar',
    10: '(status bits)',
    11: 'ft/s',
}

# Multi-Sensor Report (Type 3) field definitions, in bit order 0–7.
# Each entry: (bit, label, byte_count, is_signed, resolution, unit, std_sensor_id)
MULTI_SENSOR_FIELDS = [
    (0, 'Air Temperature',      2, True,  0.1,  '°F',  7),
    (1, 'Relative Humidity',    1, False, 1.0,  '%',   8),
    (2, 'Barometric Pressure',  2, False, 0.1,  'mBar', 9),
    (3, 'Wind Speed',           1, False, 1.0,  'mph',  4),
    (4, 'Wind Direction',       2, False, 1.0,  'deg',  5),
    (5, 'Peak Wind',            1, False, 1.0,  'mph',  6),
    (6, 'Stage',                2, True,  0.01, 'ft',   2),
    (7, 'Battery Voltage',      1, False, 0.1,  'V',    3),
]

CLOCK_STATUS_LABELS = {
    0: 'GPS-accurate; TDMA in use',
    2: 'Stale (set since power-on, now drifted); random access',
    3: 'Not set since power-on; random access',
    4: 'NTP-accurate (suitable for data, not TDMA); random access',
}

AIRLINK_ERROR_LABELS = {
    0:    'No errors',
    1:    'Bad AirLink first block (undecodable)',
    2:    'Uncorrectable symbol errors in MANT header',
    3:    'Uncorrectable symbol errors in MANT payload',
    4:    'MANT PDU length exceeds AirLink length',
    5:    'Not enough data for MANT header',
    6:    'Invalid MANT header',
    0xFF: 'Vendor-specific / freeform error',
}

MANT_ERROR_LABELS = {
    0:    'No errors',
    1:    'Inauthentic MANT (authentication failed)',
    2:    'Concentration protocol length not divisible by 4',
    0xFF: 'Vendor-specific / freeform error',
}

REPORT_TYPE_NAMES = {
    1: 'General Sensor Report',
    2: 'Tipping Bucket Rain Gage Report',
    3: 'Multi-Sensor Report',
}

VALUE_FORMAT_NAMES = {
    0: 'none',
    1: 'unsigned int',
    2: 'signed int',
    3: 'IEEE float',
}

# Protocol IDs carried in the MANT header
PROTOCOL_ID_LABELS = {
    0: 'Best-effort (no ACK)',
    1: 'Acknowledged delivery',
}

# MANT port numbers for standard application protocols
PORT_LABELS = {
    0: 'Self-Report Protocol (sensor data)',
    1: 'ALERT Concentration Protocol',
    8: 'Configuration & Control Protocol',
}

# IND API top-level command TLV types (section 8.5)
IND_COMMAND_NAMES = {
    0x00: 'ALERT2 Self-Report Protocol',
    0x01: 'ALERT2 Concentration Protocol',
    0x02: 'ALERT2 Configuration and Control',
    0x0A: 'Set Parameter',
    0x0B: 'Get Parameter',
    0x10: 'ALERT2 Data Envelope / Forward ALERT2 Messages',
    0x70: 'Initiate GPS Cycle',
    0x78: 'Save Configuration',
    0x79: 'Query Current Configuration',
    0x7A: 'Reset Configuration to Defaults',
    0x7B: 'Load Configuration',
    0x8081: 'TLV Exists',
}

# IND API parameter TLV types (section 8.6) + Message API sub-TLVs (section 8.7)
IND_PARAMETER_NAMES = {
    0x18: 'IND Address',
    0x19: 'Destination Address',
    0x1A: 'Add Path Service',
    0x1B: 'Add Destination Address',
    0x1E: 'Concentration Test Flag',
    0x20: 'Concentration PDU ID',
    0x28: 'Application PDU Timestamp Service',
    0x31: 'Address List Selection',
    0x32: 'Address List Enabled',
    0x33: 'Address List Action',
    0x34: 'Address List Type',
    0x35: 'Address List: Add List',
    0x36: 'Address List: Add Range',
    0x37: 'Address List: Remove List',
    0x38: 'Address List: Remove Range',
    0x39: 'Add Path Override',
    0x3B: 'Address List: Query',
    0x3F: 'Echo Suppression',
    0x40: 'Hop Limit',
    0x41: 'EERDS Enable',
    0x42: 'EERDS Retransmit Delay',
    0x43: 'EERDS Maximum Retransmissions',
    0x48: 'TDMA Frame Length',
    0x4A: 'TDMA Slot Length',
    0x4B: 'TDMA Slot Start Offset',
    0x4C: 'GPS Update Period',
    0x4D: 'GPS Update Timeout',
    0x4E: 'TDMA Slot Padding',
    0x4F: 'TDMA Center Transmission',
    0x50: 'Enable TDMA',
    0x51: 'TDMA Slot Overrun Behavior',
    0x52: 'TDMA Bytes Remaining',
    0x56: 'Status Report Interval (hours)',
    0x57: 'Status Report Offset (minutes)',
    0x60: 'Carrier Only Time',
    0x61: 'AGC Time',
    0x62: 'RF Tail Time',
    0x63: 'Invert Modulation',
    0x64: 'FEC Mode',
    0x65: 'Transmit Radio Always On',
    0x66: 'Transmit Radio Warm Up Time',
    0x68: 'Transmit Audio Modulation Voltage',
    0x75: 'API Version Number',
    0x77: 'Agency Identifier',
    0x7C: 'IND Time - Day/Millisecond Format',
    0x7D: 'IND Time - Extended Format',
    0x7E: 'IND Time - Seconds Since 2010',
    0x7F: 'Clock Status',
    0x96: 'Version String',
    # Message API sub-TLVs (section 8.7)
    0x14: 'AirLink PDU Envelope',
    0x15: 'MANT PDU Envelope',
    0x8400: 'MANT Header',
    0x8401: 'MANT Payload',
    0x8404: 'MANT Authentic',
    0x8405: 'MANT Error',
    0x8406: 'MANT Error Description',
    0x844C: 'AirLink Header',
    0x844D: 'AirLink Payload',
    0x844E: 'AirLink FEC Mode',
    0x844F: 'AirLink Total Symbol Errors Corrected',
    0x8450: 'AirLink Symbol Errors Corrected',
    0x8451: 'AirLink Frame Length',
    0x8452: 'AirLink Noise Level',
    0x8453: 'Number MANT PDUs Successfully Decoded',
    0x8454: 'AirLink Error',
    0x8455: 'AirLink Error Description',
    0x8080: 'Last NV-Save Status',
    0x8082: 'Encrypt Outgoing Messages',
    0x8083: 'Encryption: Address to Configure',
    0x8085: 'Encryption: Set Key',
    0x8086: 'Encryption: Remove Key',
    0x8087: 'Encryption: EMID',
}


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class DecodeError(Exception):
    """Raised when a packet cannot be decoded."""


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def parse_hex_string(s: str) -> bytes:
    """Parse a hex string with colon, space, or dash separators into bytes."""
    cleaned = re.sub(r'[:\s\-]', '', s.strip())
    if not cleaned:
        raise DecodeError('Empty input')
    if not re.fullmatch(r'[0-9A-Fa-f]+', cleaned):
        raise DecodeError('Non-hex characters found in input')
    if len(cleaned) % 2 != 0:
        raise DecodeError(f'Odd number of hex digits ({len(cleaned)}); input may be incomplete')
    return bytes.fromhex(cleaned)


def read_ext_field(data: bytes, offset: int) -> tuple:
    """
    Read an extensible 1-or-2-byte TLV type or length field.
    If bit 7 of the first byte is set the field is 2 bytes; the 15-bit value
    is (first_byte & 0x7F) << 8 | second_byte.
    Returns (value, bytes_consumed).
    """
    if offset >= len(data):
        raise DecodeError('Unexpected end of data reading TLV field')
    first = data[offset]
    if first & 0x80:
        if offset + 1 >= len(data):
            raise DecodeError('Unexpected end of data reading 2-byte TLV field')
        second = data[offset + 1]
        return ((first & 0x7F) << 8) | second, 2
    return first, 1


# ---------------------------------------------------------------------------
# Application-layer sensor value decoder
# ---------------------------------------------------------------------------

def decode_fl_value(fl_byte: int, data: bytes, offset: int) -> tuple:
    """
    Decode a sensor value using a Format/Length byte.
    Upper nibble = format (1=unsigned, 2=signed, 3=float).
    Lower nibble = byte count (0–15).
    Returns (value, bytes_consumed).  value is None when length == 0.
    """
    fmt = (fl_byte >> 4) & 0x0F
    length = fl_byte & 0x0F
    if length == 0:
        return None, 0
    end = offset + length
    if end > len(data):
        raise DecodeError(
            f'Sensor value needs {length} bytes at offset {offset} '
            f'but only {len(data) - offset} remain'
        )
    raw = data[offset:end]
    if fmt == 1:
        value = int.from_bytes(raw, 'big', signed=False)
    elif fmt == 2:
        value = int.from_bytes(raw, 'big', signed=True)
    elif fmt == 3:
        if length == 4:
            value = struct.unpack('>f', raw)[0]
        elif length == 8:
            value = struct.unpack('>d', raw)[0]
        else:
            value = int.from_bytes(raw, 'big', signed=False)
    else:
        value = int.from_bytes(raw, 'big', signed=False)
    return value, length


# ---------------------------------------------------------------------------
# Report type decoders
# ---------------------------------------------------------------------------

def decode_general_sensor_report(data: bytes) -> list:
    """
    Type 1 — General Sensor Report.
    Sensor data: [sensor_id | F/L | value] repeated.
    Returns a list of sensor dicts.
    """
    sensors = []
    offset = 0
    while offset < len(data):
        sensor_id = data[offset]
        offset += 1
        if offset >= len(data):
            raise DecodeError(f'No F/L byte after sensor ID {sensor_id} at offset {offset - 1}')
        fl_byte = data[offset]
        offset += 1
        value, consumed = decode_fl_value(fl_byte, data, offset)
        offset += consumed
        fmt_code = (fl_byte >> 4) & 0x0F
        length = fl_byte & 0x0F
        sensors.append({
            'sensor_id': sensor_id,
            'name': SENSOR_NAMES.get(sensor_id, f'Sensor #{sensor_id}'),
            'unit': SENSOR_UNITS.get(sensor_id, ''),
            'format_code': fmt_code,
            'format_name': VALUE_FORMAT_NAMES.get(fmt_code, f'format {fmt_code}'),
            'byte_length': length,
            'raw_value': value,
        })
    return sensors


def decode_tipping_bucket_report(data: bytes) -> dict:
    """
    Type 2 — Tipping Bucket Rain Gage Report.
    Structure: sensor_id | F/L | accumulator | time_offset... (1 byte each)
    """
    if len(data) < 2:
        raise DecodeError('Tipping bucket report too short (need at least 2 bytes)')
    offset = 0
    sensor_id = data[offset]; offset += 1
    fl_byte = data[offset]; offset += 1
    accum, consumed = decode_fl_value(fl_byte, data, offset)
    offset += consumed
    fmt_code = (fl_byte >> 4) & 0x0F
    length = fl_byte & 0x0F
    # Remaining bytes = 1-byte time offsets (seconds before transmission)
    time_offsets = list(data[offset:])
    return {
        'sensor_id': sensor_id,
        'name': SENSOR_NAMES.get(sensor_id, f'Sensor #{sensor_id}'),
        'format_code': fmt_code,
        'format_name': VALUE_FORMAT_NAMES.get(fmt_code, f'format {fmt_code}'),
        'accumulator_bytes': length,
        'accumulator': accum,
        'tip_count': len(time_offsets),
        'time_offsets_sec': time_offsets,
    }


def decode_multi_sensor_report(data: bytes) -> dict:
    """
    Type 3 — Multi-Sensor Report.
    Structure: flags_byte | [AT 2B] | [RH 1B] | [BP 2B] | [WS 1B] | [WD 2B] | [PW 1B] | [Stage 2B] | [BV 1B]
    Only fields with the corresponding bit set in flags are present.
    """
    if not data:
        raise DecodeError('Multi-sensor report is empty')
    flags = data[0]
    offset = 1
    sensors = []
    for bit, label, nbytes, is_signed, resolution, unit, std_id in MULTI_SENSOR_FIELDS:
        if not (flags & (1 << bit)):
            continue
        if offset + nbytes > len(data):
            raise DecodeError(f'Multi-sensor field "{label}" extends beyond data')
        raw_bytes = data[offset:offset + nbytes]
        raw_val = int.from_bytes(raw_bytes, 'big', signed=is_signed)
        eng_val = raw_val * resolution
        sensors.append({
            'bit': bit,
            'name': label,
            'sensor_id': std_id,
            'raw_value': raw_val,
            'value': round(eng_val, 4),
            'unit': unit,
            'resolution': resolution,
        })
        offset += nbytes
    return {
        'flags_byte': f'0x{flags:02X}',
        'sensors': sensors,
    }


# ---------------------------------------------------------------------------
# Application PDU decoder
# ---------------------------------------------------------------------------

def decode_apdu(data: bytes) -> dict:
    """
    Decode an ALERT2 Application PDU (= the MANT payload for Self-Report protocol).

    Returns a structured dict:
      control   — parsed control byte fields
      timestamp — optional 2-byte timestamp (seconds since last noon/midnight UTC)
      reports   — list of decoded TLV report blocks
    """
    if not data:
        raise DecodeError('Application PDU is empty')

    result = {
        'raw_hex': ':'.join(f'{b:02X}' for b in data),
        'total_bytes': len(data),
    }

    offset = 0

    # --- Control byte ---
    ctrl = data[offset]; offset += 1
    version       = ctrl & 0x03
    has_timestamp = bool(ctrl & 0x04)
    is_test       = bool(ctrl & 0x08)
    apdu_id_raw   = (ctrl >> 4) & 0x07
    has_ext       = bool(ctrl & 0x80)

    result['control'] = {
        'byte': f'0x{ctrl:02X}',
        'version': version,
        'timestamp_present': has_timestamp,
        'test_flag': is_test,
        'apdu_id': None if apdu_id_raw == 7 else apdu_id_raw,
        'apdu_id_display': f'{apdu_id_raw}' if apdu_id_raw != 7 else 'Disabled (7)',
        'extensibility': has_ext,
    }

    warnings = []
    if version != 0:
        warnings.append(f'Unexpected version {version} (expected 0)')

    # Optional second control byte (extensibility, future use)
    if has_ext:
        if offset >= len(data):
            raise DecodeError('Extensibility bit set but second control byte missing')
        offset += 1  # consume and ignore per spec

    # --- Timestamp ---
    if has_timestamp:
        if offset + 2 > len(data):
            raise DecodeError('Timestamp flag set but fewer than 2 bytes remain')
        ts_raw = (data[offset] << 8) | data[offset + 1]
        offset += 2
        h = ts_raw // 3600
        m = (ts_raw % 3600) // 60
        s = ts_raw % 60
        result['timestamp'] = {
            'raw_seconds': ts_raw,
            'display': f'{ts_raw}s ({h:02d}:{m:02d}:{s:02d} since last midnight or noon UTC)',
        }

    # --- TLV report records ---
    reports = []
    while offset < len(data):
        tlv_start = offset

        tlv_type, tbytes = read_ext_field(data, offset)
        offset += tbytes

        tlv_len, lbytes = read_ext_field(data, offset)
        offset += lbytes

        if offset + tlv_len > len(data):
            reports.append({
                'type': tlv_type,
                'type_name': REPORT_TYPE_NAMES.get(tlv_type, f'Unknown (0x{tlv_type:02X})'),
                'length': tlv_len,
                'error': f'TLV length {tlv_len} exceeds remaining data ({len(data) - offset} bytes)',
            })
            break

        tlv_value = data[offset:offset + tlv_len]
        offset += tlv_len

        report = {
            'type': tlv_type,
            'type_name': REPORT_TYPE_NAMES.get(tlv_type, f'Unknown (0x{tlv_type:02X})'),
            'length': tlv_len,
            'raw_hex': ':'.join(f'{b:02X}' for b in tlv_value),
        }

        try:
            if tlv_type == 1:
                report['sensors'] = decode_general_sensor_report(tlv_value)
            elif tlv_type == 2:
                report['tipping_bucket'] = decode_tipping_bucket_report(tlv_value)
            elif tlv_type == 3:
                report['multi_sensor'] = decode_multi_sensor_report(tlv_value)
            else:
                report['note'] = f'Unknown report type 0x{tlv_type:02X} — raw bytes shown above'
        except DecodeError as exc:
            report['error'] = str(exc)

        reports.append(report)

    result['reports'] = reports
    if warnings:
        result['warnings'] = warnings
    return result


# ---------------------------------------------------------------------------
# IND CSV format parser
# ---------------------------------------------------------------------------

def _safe_int(s: str) -> int | None:
    """Parse an integer from a CSV field, returning None if blank or invalid."""
    try:
        return int(s.strip())
    except (ValueError, AttributeError):
        return None


def decode_csv_lines(text: str) -> dict:
    """
    Parse one or more IND CSV output lines (AL22a format).
    Each line is a separate record type: AirLink, MANT, Sensor, ALERT CCN.
    """
    lines_out = []
    for raw_line in text.strip().splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if not line.startswith('AL2'):
            lines_out.append({'raw': line, 'skip': True, 'message_type': 'unknown'})
            continue

        fields = line.split(',')
        if len(fields) < 6:
            lines_out.append({'raw': line, 'error': 'Too few CSV fields', 'message_type': 'error'})
            continue

        time_sync_raw = fields[2].strip()
        ts_int = _safe_int(time_sync_raw)
        parsed = {
            'raw': line,
            'prefix': fields[0],
            'decode_timestamp': fields[1].strip(),
            'time_sync_raw': time_sync_raw,
            'time_sync_label': CLOCK_STATUS_LABELS.get(ts_int, '') if ts_int is not None else '',
            'agency': fields[3].strip(),
            'ind_address': fields[4].strip(),
            'message_type': fields[5].strip(),
        }

        rest = fields[6:]

        msg = parsed['message_type']

        if msg == 'AirLink':
            al_field_names = [
                'airlink_version', 'airlink_reserved', 'frame_length',
                'total_sym_errors', 'error_id', 'error_description',
                'raw_data', 'block_error_list', 'fec_mode', 'noise_level',
            ]
            for i, name in enumerate(al_field_names):
                parsed[name] = rest[i].strip() if i < len(rest) else ''
            err_id = _safe_int(parsed.get('error_id', '')) or 0
            parsed['error_label'] = AIRLINK_ERROR_LABELS.get(err_id, f'Error code {err_id}')
            parsed['has_error'] = err_id != 0

        elif msg == 'MANT':
            mant_field_names = [
                'mant_version', 'protocol_id', 'timestamp_request', 'add_path_request',
                'port', 'encrypted', 'reserved_bits', 'ack', 'hop_limit',
                'source_address', 'destination_address', 'pdu_id',
                'path_length', 'path', 'payload_length', 'payload',
                'error_id', 'error_description', 'mant_authentic',
            ]
            for i, name in enumerate(mant_field_names):
                parsed[name] = rest[i].strip() if i < len(rest) else ''

            err_id = _safe_int(parsed.get('error_id', '')) or 0
            parsed['error_label'] = MANT_ERROR_LABELS.get(err_id, f'Error code {err_id}')
            parsed['has_error'] = err_id != 0

            hop = _safe_int(parsed.get('hop_limit', ''))
            parsed['hop_limit_display'] = 'Unlimited (7)' if hop == 7 else str(hop)

            port_val = _safe_int(parsed.get('port', '')) or 0
            parsed['port_label'] = PORT_LABELS.get(port_val, f'Port {port_val}')

            proto_id = _safe_int(parsed.get('protocol_id', '')) or 0
            parsed['protocol_label'] = PROTOCOL_ID_LABELS.get(proto_id, f'Protocol {proto_id}')

            # Decode the MANT payload if it's port 0 (Self-Report)
            payload_hex = parsed.get('payload', '').strip()
            if payload_hex and port_val == 0:
                try:
                    payload_bytes = parse_hex_string(payload_hex)
                    parsed['decoded_apdu'] = decode_apdu(payload_bytes)
                except DecodeError as exc:
                    parsed['apdu_error'] = str(exc)
            elif payload_hex and port_val != 0:
                parsed['apdu_note'] = f'Payload decode not supported for port {port_val} ({parsed["port_label"]})'

        elif msg == 'Sensor':
            sensor_field_names = ['reading_timestamp', 'site_address', 'sensor_id', 'value']
            for i, name in enumerate(sensor_field_names):
                parsed[name] = rest[i].strip() if i < len(rest) else ''
            sid = _safe_int(parsed.get('sensor_id', ''))
            parsed['sensor_name'] = SENSOR_NAMES.get(sid, f'Sensor #{sid}') if sid is not None else ''
            parsed['sensor_unit'] = SENSOR_UNITS.get(sid, '') if sid is not None else ''

        elif msg == 'ALERT CCN':
            ccn_field_names = ['alert_timestamp', 'alert_id', 'alert_value']
            for i, name in enumerate(ccn_field_names):
                parsed[name] = rest[i].strip() if i < len(rest) else ''

        lines_out.append(parsed)

    return {'format': 'IND CSV (AL22a)', 'lines': lines_out}


# ---------------------------------------------------------------------------
# AL22b binary frame decoder
# ---------------------------------------------------------------------------

def _tlv_name(tlv_type: int) -> str:
    """Return a human-readable name for a TLV type."""
    return (
        IND_COMMAND_NAMES.get(tlv_type)
        or IND_PARAMETER_NAMES.get(tlv_type)
        or f'0x{tlv_type:X}'
    )


def _parse_tlv_sequence(data: bytes) -> list:
    """
    Parse a flat sequence of extensible TLVs.
    Returns a list of dicts: {type, type_hex, type_name, length, raw_hex, value_bytes}.
    """
    tlvs = []
    offset = 0
    while offset < len(data):
        tlv_type, tbytes = read_ext_field(data, offset)
        offset += tbytes
        if offset >= len(data):
            tlvs.append({'type': tlv_type, 'type_hex': f'0x{tlv_type:X}',
                         'type_name': _tlv_name(tlv_type),
                         'error': 'Missing length field'})
            break
        tlv_len, lbytes = read_ext_field(data, offset)
        offset += lbytes
        end = offset + tlv_len
        if end > len(data):
            tlvs.append({'type': tlv_type, 'type_hex': f'0x{tlv_type:X}',
                         'type_name': _tlv_name(tlv_type), 'length': tlv_len,
                         'error': f'Length {tlv_len} exceeds remaining data ({len(data) - offset} bytes)'})
            break
        value_bytes = data[offset:end]
        offset = end
        tlvs.append({
            'type': tlv_type,
            'type_hex': f'0x{tlv_type:X}',
            'type_name': _tlv_name(tlv_type),
            'length': tlv_len,
            'raw_hex': ':'.join(f'{b:02X}' for b in value_bytes),
            'value_bytes': value_bytes,
        })
    return tlvs


def _decode_parameter_tlvs(data: bytes) -> list:
    """Decode a sequence of parameter TLVs (inside Set/Get Parameter)."""
    params = []
    for p in _parse_tlv_sequence(data):
        param = {
            'type': p['type'],
            'type_hex': p['type_hex'],
            'name': IND_PARAMETER_NAMES.get(p['type'], f'Parameter {p["type_hex"]}'),
            'length': p.get('length', 0),
            'raw_hex': p.get('raw_hex', ''),
        }
        if 'error' in p:
            param['error'] = p['error']
        val = p.get('value_bytes', b'')
        if val:
            if len(val) <= 4:
                param['value_int'] = int.from_bytes(val, 'big')
            # Try ASCII string (Agency ID, Version String, etc.)
            try:
                decoded = val.decode('ascii')
                if all(32 <= ord(c) < 127 for c in decoded):
                    param['value_str'] = decoded
            except Exception:
                pass
        params.append(param)
    return params


def _decode_mant_envelope(data: bytes) -> dict:
    """Decode MANT PDU Envelope contents."""
    result = {}
    for tlv in _parse_tlv_sequence(data):
        t, val = tlv['type'], tlv.get('value_bytes', b'')
        if t == 0x8404:  # MANT Authentic
            result['authentic'] = bool(int.from_bytes(val, 'big')) if val else False
        elif t == 0x8400:  # MANT Header
            result['header_hex'] = tlv.get('raw_hex', '')
        elif t == 0x8401:  # MANT Payload = APDU
            result['payload_hex'] = tlv.get('raw_hex', '')
            try:
                result['apdu'] = decode_apdu(val)
            except DecodeError as exc:
                result['apdu_error'] = str(exc)
        elif t == 0x8405:  # MANT Error
            code = int.from_bytes(val, 'big') if val else 0
            result['mant_error'] = {'code': code, 'label': MANT_ERROR_LABELS.get(code, f'Code {code}')}
        elif t == 0x8406:  # MANT Error Description
            try:
                result['mant_error_desc'] = val.decode('ascii', errors='replace')
            except Exception:
                result['mant_error_desc'] = tlv.get('raw_hex', '')
    return result


def _decode_airlink_envelope(data: bytes) -> dict:
    """Decode AirLink PDU Envelope contents."""
    result = {}
    for tlv in _parse_tlv_sequence(data):
        t, val = tlv['type'], tlv.get('value_bytes', b'')
        int_val = int.from_bytes(val, 'big') if val else 0
        if t == 0x8451:
            result['frame_length'] = int_val
        elif t == 0x844F:
            result['total_sym_errors'] = int_val
        elif t == 0x8450:
            result['per_block_errors'] = list(val)
        elif t == 0x8452:
            result['noise_level'] = int_val
        elif t == 0x844E:
            result['fec_mode'] = int_val
        elif t == 0x8453:
            result['num_mant_pdus'] = int_val
        elif t == 0x8454:
            result['airlink_error'] = {'code': int_val, 'label': AIRLINK_ERROR_LABELS.get(int_val, f'Code {int_val}')}
        elif t == 0x8455:
            try:
                result['airlink_error_desc'] = val.decode('ascii', errors='replace')
            except Exception:
                result['airlink_error_desc'] = tlv.get('raw_hex', '')
        elif t == 0x844C:
            result['airlink_header'] = tlv.get('raw_hex', '')
        elif t == 0x844D:
            result['airlink_payload'] = tlv.get('raw_hex', '')
    return result


def _decode_data_envelope(data: bytes) -> dict:
    """Decode ALERT2 Data Envelope (type 0x10) — Message API output from IND."""
    result = {}
    for tlv in _parse_tlv_sequence(data):
        t, val = tlv['type'], tlv.get('value_bytes', b'')
        if t == 0x77:  # Agency Identifier
            try:
                result['agency_id'] = val.decode('ascii', errors='replace')
            except Exception:
                result['agency_id'] = tlv.get('raw_hex', '')
        elif t == 0x7D:  # IND Time - Extended Format
            result['timestamp_hex'] = tlv.get('raw_hex', '')
        elif t == 0x7F:  # Clock Status
            cs = val[0] if val else 0
            result['clock_status'] = {'value': cs, 'label': CLOCK_STATUS_LABELS.get(cs, f'Status {cs}')}
        elif t == 0x18:  # Decoding IND Address
            result['ind_address'] = int.from_bytes(val, 'big') if val else 0
        elif t == 0x14:  # AirLink PDU Envelope
            result['airlink_envelope'] = _decode_airlink_envelope(val)
        elif t == 0x15:  # MANT PDU Envelope
            result['mant_envelope'] = _decode_mant_envelope(val)
        else:
            result.setdefault('other_tlvs', []).append({
                'name': _tlv_name(t), 'type_hex': f'0x{t:X}', 'raw_hex': tlv.get('raw_hex', '')
            })
    return result


def _decode_frame_tlv(tlv_type: int, value_bytes: bytes) -> dict:
    """
    Decode a single top-level TLV from an AL22b binary frame.
    Returns a dict with decoded contents merged into the base tlv info.
    """
    t, val = tlv_type, value_bytes

    if t == 0x00:  # Self-Report Protocol — value IS the APDU
        try:
            return {'apdu': decode_apdu(val)}
        except DecodeError as exc:
            return {'error': str(exc)}

    elif t in (0x0A, 0x0B):  # Set Parameter / Get Parameter
        return {'parameters': _decode_parameter_tlvs(val)}

    elif t == 0x10:  # ALERT2 Data Envelope (Message API output)
        return {'data_envelope': _decode_data_envelope(val)}

    elif t == 0x02:  # Config and Control — contains nested IND API TLVs
        nested_tlvs = _parse_tlv_sequence(val)
        nested_decoded = []
        for nt in nested_tlvs:
            entry = {k: v for k, v in nt.items() if k != 'value_bytes'}
            sub = _decode_frame_tlv(nt['type'], nt.get('value_bytes', b''))
            entry.update(sub)
            nested_decoded.append(entry)
        return {'nested_tlvs': nested_decoded}

    # Commands with no value or trivial value (Save, Query, Reset, Load, GPS Cycle)
    elif t in (0x70, 0x78, 0x79, 0x7A, 0x7B):
        return {}

    return {}


def decode_binary_frame(data: bytes) -> dict:
    """
    Decode a full AL22b binary IND API / Message API frame.
    Structure: b'AL22b' (5 bytes) | total_length (extensible 1-2 bytes) | TLV data
    """
    _PREFIX = b'AL22b'
    if len(data) < len(_PREFIX) + 1 or data[:5] != _PREFIX:
        raise DecodeError('Not a valid AL22b binary frame (wrong prefix)')

    offset = 5
    total_len, lbytes = read_ext_field(data, offset)
    offset += lbytes

    frame_end = offset + total_len
    if frame_end > len(data):
        raise DecodeError(
            f'Frame total_length={total_len} but only {len(data) - offset} bytes remain after length field'
        )

    frame_bytes = data[offset:frame_end]
    raw_tlvs = _parse_tlv_sequence(frame_bytes)

    tlvs = []
    for rt in raw_tlvs:
        entry = {k: v for k, v in rt.items() if k != 'value_bytes'}
        if 'error' not in rt:
            decoded = _decode_frame_tlv(rt['type'], rt.get('value_bytes', b''))
            entry.update(decoded)
        tlvs.append(entry)

    return {
        'prefix': 'AL22b',
        'total_length': total_len,
        'raw_hex': ':'.join(f'{b:02X}' for b in data),
        'tlvs': tlvs,
    }


# ---------------------------------------------------------------------------
# Top-level entry points
# ---------------------------------------------------------------------------

_AL22B_HEX_PREFIX = '414C323262'  # "AL22b" as uppercase hex


def _detect_format(text: str) -> str:
    s = text.strip()
    # Text CSV format (AL22a)
    if s.startswith('AL22a') or s.startswith('AL2'):
        return 'csv'
    # Binary frame: hex string whose decoded bytes start with "AL22b"
    cleaned = re.sub(r'[:\s\-]', '', s).upper()
    if cleaned.startswith(_AL22B_HEX_PREFIX):
        return 'binary_frame'
    return 'hex_payload'


def decode_packet(input_text: str) -> dict:
    """
    Auto-detect the input format and decode the packet.
    Returns a result dict suitable for template rendering.
    """
    if not input_text or not input_text.strip():
        raise DecodeError('No input provided')

    fmt = _detect_format(input_text)

    if fmt == 'csv':
        result = decode_csv_lines(input_text)
        result['input_format'] = 'IND CSV (AL22a)'
        result['valid'] = any(
            'error' not in line and not line.get('skip')
            for line in result.get('lines', [])
        )
        return result

    # Both binary_frame and hex_payload need the bytes first
    try:
        raw_bytes = parse_hex_string(input_text.strip())
    except DecodeError as exc:
        return {
            'input_format': 'Hex',
            'valid': False,
            'error': str(exc),
        }

    if fmt == 'binary_frame':
        try:
            frame = decode_binary_frame(raw_bytes)
            return {
                'input_format': 'AL22b Binary IND API Frame',
                'valid': True,
                'binary_frame': frame,
            }
        except DecodeError as exc:
            return {
                'input_format': 'AL22b Binary Frame',
                'valid': False,
                'error': str(exc),
            }

    # Hex payload — treat as raw MANT Application PDU
    try:
        apdu = decode_apdu(raw_bytes)
        return {
            'input_format': 'Hex Payload (MANT Application PDU)',
            'valid': True,
            'apdu': apdu,
        }
    except DecodeError as exc:
        return {
            'input_format': 'Hex Payload',
            'valid': False,
            'error': str(exc),
        }


def _apdu_summary_parts(apdu: dict) -> list:
    """Extract sensor reading strings from a decoded APDU dict."""
    parts = []
    for rpt in apdu.get('reports', []):
        if 'sensors' in rpt:
            for s in rpt['sensors']:
                unit = s.get('unit', '')
                parts.append(f"{s['name']}: {s['raw_value']}{(' ' + unit) if unit else ''}")
        elif 'tipping_bucket' in rpt:
            tb = rpt['tipping_bucket']
            parts.append(f"Rain accum={tb['accumulator']} ({tb['tip_count']} tips)")
        elif 'multi_sensor' in rpt:
            for s in rpt['multi_sensor']['sensors']:
                parts.append(f"{s['name']}: {s['value']} {s['unit']}")
    return parts


def _build_sensor_summary(result: dict) -> str:
    """Build a short human-readable summary of sensor readings from a decode result."""
    parts = []
    if 'apdu' in result:
        parts.extend(_apdu_summary_parts(result['apdu']))
    elif 'binary_frame' in result:
        for tlv in result['binary_frame'].get('tlvs', []):
            if 'apdu' in tlv:
                parts.extend(_apdu_summary_parts(tlv['apdu']))
            # Message API path: data_envelope → mant_envelope → apdu
            de = tlv.get('data_envelope', {})
            apdu = de.get('mant_envelope', {}).get('apdu')
            if apdu:
                parts.extend(_apdu_summary_parts(apdu))
    elif 'lines' in result:
        for line in result['lines']:
            if line.get('message_type') == 'Sensor':
                parts.append(
                    f"Site {line.get('site_address')} "
                    f"Sensor {line.get('sensor_id')} ({line.get('sensor_name', '')}): "
                    f"{line.get('value')} {line.get('sensor_unit', '')}"
                )
    return '; '.join(parts)


def decode_single_for_batch(raw: str) -> dict:
    """
    Decode one line for batch processing. Returns a minimal result dict.
    """
    raw = raw.strip()
    if not raw:
        return {'valid': False, 'reason': 'Empty line', 'raw': raw, 'summary': ''}

    try:
        result = decode_packet(raw)
    except DecodeError as exc:
        return {'valid': False, 'reason': str(exc), 'raw': raw, 'summary': ''}
    except Exception as exc:
        return {'valid': False, 'reason': f'Unexpected error: {exc}', 'raw': raw, 'summary': ''}

    if not result.get('valid', False):
        return {
            'valid': False,
            'reason': result.get('error', 'Parse error'),
            'raw': raw,
            'summary': '',
            'result': result,
        }

    return {
        'valid': True,
        'reason': '',
        'raw': raw,
        'summary': _build_sensor_summary(result),
        'result': result,
    }

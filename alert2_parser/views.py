from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from .decoder import decode_packet, decode_single_for_batch


@login_required
@require_http_methods(['GET', 'POST'])
def decode_view(request):
    packet_input = ''
    result = None
    error = None

    if request.method == 'POST':
        packet_input = request.POST.get('packet', '').strip()
    else:
        packet_input = request.GET.get('packet', '').strip()

    if packet_input:
        try:
            result = decode_packet(packet_input)
            if not result.get('valid', False) and 'error' in result:
                error = result['error']
        except Exception as exc:
            error = str(exc)

    return render(request, 'alert2_parser/decode.html', {
        'packet_input': packet_input,
        'result': result,
        'error': error,
    })


@login_required
@require_http_methods(['GET', 'POST'])
def batch_view(request):
    rows = None
    filename = None
    error = None

    if request.method == 'POST' and 'packet_file' in request.FILES:
        f = request.FILES['packet_file']
        filename = f.name
        try:
            text = f.read().decode('utf-8', errors='replace')
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            rows = []
            for i, line in enumerate(lines, start=1):
                row = decode_single_for_batch(line)
                row['line_no'] = i
                row['truncated_raw'] = (line[:80] + '…') if len(line) > 80 else line
                rows.append(row)
        except Exception as exc:
            error = f'File read error: {exc}'

    return render(request, 'alert2_parser/batch.html', {
        'rows': rows,
        'filename': filename,
        'error': error,
    })

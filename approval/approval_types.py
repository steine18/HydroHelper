def _yn(key, number, text, conditional_on=None, conditional_value='yes', guidance=None, good_response='yes', options=None):
    if options is None:
        # good_response: 'yes', 'no', or 'both'
        good_set = {'yes', 'no'} if good_response == 'both' else {good_response}
        yes_opt = {'value': 'yes', 'label': 'Yes', 'good': 'yes' in good_set}
        no_opt  = {'value': 'no',  'label': 'No',  'good': 'no'  in good_set}
        na_opt  = {'value': 'na',  'label': 'N/A', 'good': False}
        # Good options first, then bad, N/A always last
        ordered = sorted([yes_opt, no_opt], key=lambda o: (0 if o['good'] else 1))
        options = ordered + [na_opt]
    item = {'type': 'yn', 'key': key, 'number': number, 'text': text, 'options': options}
    if conditional_on:
        item['conditional_on'] = conditional_on
        item['conditional_value'] = conditional_value
    if guidance:
        item['guidance'] = guidance
    return item


def _date(key, number, text, conditional_on=None, conditional_value='yes', color_from=None):
    item = {'type': 'date', 'key': key, 'number': number, 'text': text}
    if conditional_on:
        item['conditional_on'] = conditional_on
        item['conditional_value'] = conditional_value
    if color_from:
        item['color_from'] = color_from
    return item


def _text(key, number, text):
    return {'type': 'text', 'key': key, 'number': number, 'text': text}


def _section(number, title):
    return {'type': 'section', 'number': number, 'title': title}


_UP_TO_DATE_OPTIONS = [
    {'value': 'up_to_date', 'label': 'Up to date', 'good': True},
    {'value': 'yes',        'label': 'Yes',         'good': True},
    {'value': 'no',         'label': 'No',          'good': False},
    {'value': 'na',         'label': 'N/A',         'good': False},
]

_NO_CORRECTIONS_OPTIONS = [
    {'value': 'no_corrections', 'label': 'No corrections', 'good': True},
    {'value': 'yes',            'label': 'Yes',             'good': True},
    {'value': 'no',             'label': 'No',              'good': False},
    {'value': 'na',             'label': 'N/A',             'good': False},
]


APPROVAL_TYPES = {
    'stage_discharge': {
        'label': 'Stage/Discharge',
        'items': [
            _section(1, 'Discharge Measurements, Field Notes, Level Notes, Station Description'),
            _yn('q1_1', '1.1', 'Were discharge measurements, field notes, and level notes adequately reviewed (and corrected, if necessary) and were these reviews documented in accordance with WSC procedures? (if not, this task must be completed before approval)'),
            _yn('q1_2', '1.2', 'Have measurements, field notes, level notes, and other information been properly stored / archived in accordance with WSC procedures?'),
            _yn('q1_3', '1.3', 'Has the Station Description been properly updated to reflect any changes that occurred or were made during the analysis period?', options=_UP_TO_DATE_OPTIONS),

            _section(2, 'Levels'),
            _date('q2_1', '2.1', 'Date of last levels:', color_from='q2_2'),
            _yn('q2_2', '2.2', 'Are levels overdue?', good_response='no', guidance='If levels are overdue, or determined to be invalid, analysis period should not be approved until levels are run. If levels are overdue and the record is analyzed and then approved, revisions may be required as per established revision criteria. Levels frequency requirements: 1 year for new sites until 3 sets of levels are run; 1 year for new sites with new reference gage installation until 3 sets of levels are run; 1 year for sites where a datum correction was determined from previous levels; 3 years for long-term sites; 5 years for long-term stable sites (there should be documentation of stability).'),
            _yn('q2_3', '2.3', 'Were levels run during the analysis period? (if no, go on to section 3)', good_response='both'),
            _yn('q2_3_1', '2.3.1', 'Were levels done in compliance with T&M 3-A19 (if not, period cannot be approved until a valid set of levels is run as outlined in Appendix E, p. 59)?', conditional_on='q2_3'),
            _yn('q2_3_2', '2.3.2', 'Have levels data been updated in the Historic Levels Summary and Station Description, and are those data accurate?', conditional_on='q2_3'),
            _yn('q2_4', '2.4', 'Was a datum correction of 0.015 ft or more identified? (if no, go on to section 3)', good_response='both'),
            _yn('q2_4_1', '2.4.1', 'Was datum correction input into proper correction set (Set 1)?', conditional_on='q2_4'),
            _yn('q2_4_2', '2.4.2', 'Does the magnitude of the applied correction agree with the difference between gage datum and the reference gage found during levels?', conditional_on='q2_4'),
            _yn('q2_4_3', '2.4.3', 'Is the presumed cause for the datum correction explained in the station analysis and is the explanation valid?', conditional_on='q2_4'),
            _yn('q2_4_4', '2.4.4', 'Does application of the correction (prorated or constant) to the time series agree with the presumed cause and explanation provided in the station analysis?', conditional_on='q2_4'),
            _yn('q2_4_5', '2.4.5', 'Were reference gage readings made during site visits, and gage heights associated with discharge measurements, properly adjusted based upon the datum correction?', conditional_on='q2_4'),
            _yn('q2_4_6', '2.4.6', 'Does application of the correction extend into a period of previously approved data? If so, was the approved period evaluated in accordance with applicable revision criteria?', conditional_on='q2_4'),

            _section(3, 'Gage-Height Edits'),
            _yn('q3_1', '3.1', 'Were erroneous recorded gage heights removed?'),
            _yn('q3_1_1', '3.1.1', 'Was the basis for removal adequately discussed in the station analysis?', conditional_on='q3_1'),
            _yn('q3_2', '3.2', 'Were backup data available, downloaded, and used to fill any gaps in transmissions?'),
            _yn('q3_2_1', '3.2.1', 'Were these steps adequately discussed in the station analysis?', conditional_on='q3_2'),
            _yn('q3_3', '3.3', 'Were periods of ice affected recorded gage heights properly identified and discussed?',
                options=[
                    {'value': 'no_ice', 'label': 'No Ice', 'good': True},
                    {'value': 'yes',    'label': 'Yes',    'good': True},
                    {'value': 'no',     'label': 'No',     'good': False},
                    {'value': 'na',     'label': 'N/A',    'good': False},
                ]),

            _section(4, 'Gage-Height Corrections'),
            _yn('q4_1', '4.1', 'Do gage-height correction values agree with differences observed between reference gage and recorder? (examine field notes and compare reference gage and recorder readings to defined gage height correction values)'),
            _yn('q4_2', '4.2', 'Is the applied timing of each gage height correction valid, and does it agree with the rationale provided in the station analysis?'),
            _yn('q4_3', '4.3', 'Have larger corrections (> 0.03 ft) been adequately discussed? (Note: Blanket statements for small instrument drift can be provided. Larger corrections require detailed discussion.)'),
            _yn('q4_4', '4.4', 'Were gage-height corrections properly entered using correction set 2?'),

            _section(5, 'Other Types of Data Corrections'),
            _yn('q5_1', '5.1', 'Were other types of data corrections (flushing, purging, drawdown, etc.) defined and applied during the analysis period? (if no, go on to section 6)', good_response='both'),
            _yn('q5_2', '5.2', 'Were flushing or purge corrections defined and applied? (if no, go on to section 5.3)', conditional_on='q5_1', good_response='both'),
            _yn('q5_2_1', '5.2.1', 'Do flushing or purge correction values agree with differences observed between reference gage and recorder both pre- and post-flush / purge? (examine field notes and compare the difference between reference gage and recorder readings to input correction values)', conditional_on='q5_2'),
            _yn('q5_2_2', '5.2.2', 'Is the timing of application of flushing / purge corrections valid and does it agree with the rationale provided in station analysis?', conditional_on='q5_2'),
            _yn('q5_2_3', '5.2.3', 'Were flushing / purge corrections properly entered using correction set 3?', conditional_on='q5_2'),
            _yn('q5_3', '5.3', 'Were drawdown corrections defined and applied? (if no, go on to section 6)', conditional_on='q5_1', good_response='both'),
            _yn('q5_3_1', '5.3.1', 'Was the drawdown correction curve based upon direct observations of the reference gage and recorder over a range of stage consistent with the variable correction applied in the record? (plots of observations should be referenced and archived)', conditional_on='q5_3'),
            _yn('q5_3_2', '5.3.2', 'Was the basis of the drawdown correction curve adequately discussed in station analysis?', conditional_on='q5_3'),
            _yn('q5_3_3', '5.3.3', 'Is timing of the applications of drawdown corrections valid and does it agree with the rationale provided in the station analysis? (note: drawdown corrections should be active throughout time period and the relation to stage consistent so long as the orifice configuration associated with drawdown remains the same)', conditional_on='q5_3'),
            _yn('q5_3_4', '5.3.4', 'Were drawdown corrections properly input using correction set 3?', conditional_on='q5_3'),

            _section(6, 'Peak Stage'),
            _yn('q6_1', '6.1', 'Were peak stage values verified according to the requirements of OSW TM 14.06? Assess validity of reasoning provided.'),
            _yn('q6_2', '6.2', 'Was a comparison of the verified peaks for the analysis period to the previous peaks for the water year provided in the station analysis? If analysis period spans the water year boundary, verify the peak stage value for the water year.'),

            _section(7, 'Stage-Discharge Relation'),
            _yn('q7_1', '7.1', 'Have all ratings that were active during the analysis period been documented and approved in accordance with WSC procedures? (if not, this task must be completed before approval)'),
            _yn('q7_2', '7.2', 'Does the active rating represent the current stage-discharge relation as indicated by documented control features and the plotting position of recent measurements made under clear control conditions?'),
            _yn('q7_3', '7.3', 'Have recent measurements been made that cover the range of computed discharge for the analysis period?'),

            _section(8, 'Shift Curves'),
            _yn('q8_1', '8.1', 'Are developed shift curves consistent with the shape of the base rating?'),
            _yn('q8_2', '8.2', 'Are developed shift curves associated with the same control feature consistent with one another (similar hinge and merge gage heights)?'),
            _yn('q8_3', '8.3', 'Are shift curves applicable to a specific hydraulic control feature sound and are they drawn such that they merge with the base rating at an appropriate gage height (usually in the transition between controls)? If not, has a valid explanation been provided?'),
            _yn('q8_4', '8.4', 'Have shapes of the shift curves been adequately explained with respect to selected hinge and merge gage heights, and with the hydraulic control?'),

            _section(9, 'Application of Shift Curves'),
            _yn('q9_1', '9.1', 'Does the timing of the application of the developed shift curves agree with the interpretation of the cause for the identified shift?'),
            _yn('q9_2', '9.2', 'Has the timing of the application of shift curves been adequately explained with respect to the hydrograph?'),

            _section(10, 'Estimates'),
            _yn('q10_1', '10.1', 'Are estimates appropriate, consistent, and developed using adequate methods and with due consideration of all available information? Has that information been documented appropriately?'),

            _section(11, 'Hydrographic Comparison'),
            _yn('q11_1', '11.1', 'Have hydrographic comparisons been adequately made and discussed (regardless of whether any data were estimated)? Have comparison plots been archived? If no comparison site is available, has a statement to that effect been provided in the analysis?'),

            _section(12, 'Peak Streamflow'),
            _yn('q12_1', '12.1', 'Have maximum computed peak streamflow values been adequately determined?'),
            _yn('q12_2', '12.2', 'Was a comparison of the computed peak streamflows for the analysis period to the previous peak streamflows for the water year contained in the station analysis? If analysis period spans the water year boundary, verify the peak streamflow for the water year.'),

            _section(13, 'Daily Values'),
            _yn('q13_1', '13.1', 'Examine computed daily values for accuracy, completeness and proper use of qualifiers.'),

            _section(14, 'Manuscript'),
            _yn('q14_1', '14.1', 'Have SIMS Manuscript elements been updated as needed?', options=_UP_TO_DATE_OPTIONS),

            _section(15, 'Approval Summary'),
            _text('q15', '15', 'Provide brief assessment of the analysis period in context of the findings outlined above. Discuss analyst\'s evaluation / quality rating of both stage and computed discharge record and provide your evaluation.'),

            _section(16, 'Operational Follow Up'),
            _text('q16', '16', 'List suggested follow-up such as corrective actions or other needed information, measurements, or observations.'),
        ],
    },

    'precipitation': {
        'label': 'Precipitation',
        'items': [
            _section(1, 'Field Notes, Calibration Notes, Station Description'),
            _yn('q1_1', '1.1', 'Were field notes, and calibration notes adequately reviewed and were these reviews documented in accordance with WSC procedures? (if not, this task must be completed before approval)'),
            _yn('q1_2', '1.2', 'Have measurements, field notes, level notes, and other information been properly stored / archived in accordance with WSC procedures?'),
            _yn('q1_3', '1.3', 'Has the Station Description been properly updated to reflect any changes made or observed during analysis period?', options=_UP_TO_DATE_OPTIONS),

            _section(2, 'Calibrations'),
            _date('q2_1', '2.1', 'Date of last calibration:'),
            _yn('q2_2', '2.2', 'Is a calibration overdue?', good_response='no', guidance='Although calibrations are not required for analysis, precipitation records cannot be approved without \'bookending\' successful calibrations. Annual calibrations are required; if water year is complete and a calibration has not been performed, a calibration should be scheduled immediately. If more frequent approval is desired, then WSC policy regarding calibration frequency should be revised accordingly.'),
            _yn('q2_3', '2.3', 'Was the instrument replaced or calibrated during the analysis period? (if no, go on to section 3)', good_response='both'),
            _yn('q2_3_1', '2.3.1', 'Was the calibration done in compliance with OSW TM 2006.01 and documented following procedures outlined in the WSC\'s Quality Assurance Plan (if not, period cannot be approved until a valid calibration is performed/documented)?', conditional_on='q2_3'),
            _yn('q2_4', '2.4', 'Did the calibration error exceed 5%? (if no, go on to section 3)', good_response='no'),
            _yn('q2_4_1', '2.4.1', 'If the calibration error exceeded 10%, have all data collected since the last successful calibration been totally removed from the database?', conditional_on='q2_4'),
            _yn('q2_4_2', '2.4.2', 'Have remediation actions been fully documented (instrument replaced, leveled or other reparations made, followed by a successful calibration)?', conditional_on='q2_4'),

            _section(3, 'Edits'),
            _yn('q3_1', '3.1', 'Were periods of erroneous recorded precipitation amounts (due to clogs, snow/ice, and damage to gage) removed?'),
            _yn('q3_1_1', '3.1.1', 'Was this adequately discussed in the station analysis?', conditional_on='q3_1'),
            _yn('q3_2', '3.2', 'Was backup data available, downloaded, and used to fill any gaps in transmissions?'),
            _yn('q3_2_1', '3.2.1', 'Was this adequately discussed in the station analysis?', conditional_on='q3_2'),

            _section(4, 'Corrections'),
            _text('q4', '4', 'Corrections should generally not be applied without compelling justifications as to the amount and timing. When applied, ensure the rationale and implementation are adequate.'),

            _section(5, 'Estimates'),
            _yn('q5', '5', 'Are estimates appropriate, consistent, and developed using recommended methods and with due consideration of all available information?'),

            _section(6, 'Hyetographic Comparison'),
            _yn('q6', '6', 'Have hyetographic comparisons been adequately made and discussed?'),

            _section(7, 'Daily Values'),
            _yn('q7_1', '7.1', 'Examine computed daily values for accuracy, completeness and proper use of qualifiers.'),

            _section(8, 'Manuscript'),
            _yn('q8_1', '8.1', 'Have SIMS Manuscript elements been updated as needed?', options=_UP_TO_DATE_OPTIONS),

            _section(9, 'Approval Evaluation'),
            _text('q9', '9', 'Provide brief assessment of the analysis period in context of the findings outlined above. Discuss analyst\'s evaluation of record and provide your evaluation.'),

            _section(10, 'Operational Follow Up'),
            _text('q10', '10', 'List suggested follow-up such as corrective actions or other needed information, measurements, or observations.'),
        ],
    },

    'groundwater': {
        'label': 'Groundwater',
        'items': [
            _section(1, 'Discrete Data'),
            _yn('q1_1', '1.1', 'Were discrete water-level data entered into GWSI?'),
            _yn('q1_2', '1.2', 'Were all corrections applied properly to the discrete data, including corrections related to tape calibration, measuring point, and datum changes?'),
            _yn('q1_3', '1.3', 'Was a hydrograph of new and historic discrete values created and reviewed?'),
            _yn('q1_4', '1.4', 'Were water-level measurement policies followed?'),
            _yn('q1_5', '1.5', 'Were SVMobileAQ XML files or other original record archived?'),
            _yn('q1_6', '1.6', 'Were discrete data discussed in the Station Analysis?'),

            _section(2, 'Field Notes'),
            _yn('q2_1', '2.1', 'Were routine and non-routine field-visit activities documented?'),
            _yn('q2_2', '2.2', 'Were field notes adequately reviewed for completeness and accuracy (and corrected, if necessary)?'),
            _yn('q2_3', '2.3', 'Were reviews documented in accordance with WSC procedures? (if not, this task must be completed before approval)'),

            _section(3, 'Station Level Notes'),
            _yn('q3_1', '3.1', 'Was the date of last visual/manual check of vertical relationship between measuring point and reference marks documented?'),
            _yn('q3_2', '3.2', 'Are levels or reference point inspections overdue? If stable, confirm every 3 to 5 years.', good_response='no'),
            _date('q3_3', '3.3', 'Date of last station levels:', color_from='q3_2'),
            _yn('q3_4', '3.4', 'Were levels run during the record period?', good_response='both'),
            _yn('q3_4_1', '3.4.1', 'Have levels data been reviewed for accuracy?', conditional_on='q3_4'),
            _yn('q3_4_2', '3.4.2', 'Have levels been updated in the Historic Levels Summary and Station Description?', conditional_on='q3_4'),
            _yn('q3_5', '3.5', 'Was a datum correction identified? (if no, go on to section 4)', good_response='both'),
            _yn('q3_5_1', '3.5.1', 'Is the presumed cause for the datum correction explained in the Station Analysis and is the explanation valid?', conditional_on='q3_5'),
            _yn('q3_5_2', '3.5.2', 'Does the application of the correction to the time series agree with the presumed cause and explanation?', conditional_on='q3_5'),
            _yn('q3_5_3', '3.5.3', 'Were discrete water-level measurements properly adjusted for the period based upon the datum correction?', conditional_on='q3_5'),
            _yn('q3_5_4', '3.5.4', 'Were land surface datum and datum history updated in NWIS?', conditional_on='q3_5'),
            _yn('q3_5_5', '3.5.5', 'Does the application of the correction extend into a period of previously approved data? If so, was the approved period evaluated in accordance with applicable revision criteria?', conditional_on='q3_5'),

            _section(4, 'Station Description'),
            _yn('q4_1', '4.1', 'Was the Station Description updated to reflect any changes that occurred or were made during the record period?', options=_UP_TO_DATE_OPTIONS),

            _section(5, 'Water-Level Edits'),
            _yn('q5_1', '5.1', 'Check instantaneous values for periods of missing data and spikes/anomalies.'),
            _yn('q5_2', '5.2', 'Are thresholds set to adequately manage data spikes or anomalies?'),

            _section(6, 'Water-Level Corrections'),
            _yn('q6_1', '6.1', 'Are water-level corrections reasonable for the site conditions and measurement method limitations?', options=_NO_CORRECTIONS_OPTIONS),
            _yn('q6_2', '6.2', 'Do applied water-level corrections agree with reasons provided in Station Analysis?', options=_NO_CORRECTIONS_OPTIONS),
            _yn('q6_3', '6.3', 'Are water-level corrections applied correctly in the database?', options=_NO_CORRECTIONS_OPTIONS),

            _section(7, 'Qualifiers and Other Metadata'),
            _yn('q7_1', '7.1', 'Are appropriate data qualifiers assigned or otherwise described as expected by use of metadata?', options=[
                {'value': 'no_qualifiers', 'label': 'No qualifiers', 'good': True},
                {'value': 'yes',           'label': 'Yes',           'good': True},
                {'value': 'no',            'label': 'No',            'good': False},
                {'value': 'na',            'label': 'N/A',           'good': False},
            ]),

            _section(8, 'Daily Values'),
            _yn('q8_1', '8.1', 'Are partial days adequately labeled and does the time-series software show evidence that they have been reviewed?'),

            _section(9, 'Hydrographic Comparison and Review'),
            _yn('q9_1', '9.1', 'Have hydrographic comparisons been adequately made and discussed?'),
            _yn('q9_2', '9.2', 'Does the period reviewed look reasonable when compared to the period of record?'),

            _section(10, 'Manuscript'),
            _yn('q10_1', '10.1', 'Have SIMS Manuscript elements been updated as needed?', options=_UP_TO_DATE_OPTIONS),

            _section(11, 'Approval Summary'),
            _text('q11', '11', 'Provide brief assessment of the record period in context of the findings outlined above. Discuss analyst\'s evaluation and quality of groundwater level record. Add the approval summary to the Approval Comments for the period in RMS.'),
        ],
    },
}

APPROVAL_TYPES_BY_ID = APPROVAL_TYPES
APPROVAL_TYPE_CHOICES = [(k, v['label']) for k, v in APPROVAL_TYPES.items()]

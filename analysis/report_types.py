REPORT_TYPES = [
    {
        "id": "stage_discharge",
        "label": "Stage/Discharge Analysis",
        "sections": [
            {
                "key": "gage_height_record",
                "title": "Gage Height Record",
                "guidance": (
                    "State the quality of the gage height record (good, fair, poor) for the analysis "
                    "period. State the range of stage experienced during analysis period (min and max). "
                    "Include general discussion of periods with any problems (missing record, for example)."
                ),
            },
            {
                "key": "datum",
                "title": "Datum",
                "guidance": (
                    "Provide the date of the most recent levels. If run during analysis period, discuss "
                    "the results of the level run, provide the reasoning / justification for any datum "
                    "correction, and explain how the datum correction was applied, include dates."
                ),
            },
            {
                "key": "backup_data",
                "title": "Backup Data",
                "guidance": (
                    "Describe source of the backup data (EDL, etc.), the quality of the backup data, "
                    "why there was a gap in the primary time-series, and the period that contains the "
                    "merged data."
                ),
            },
            {
                "key": "ice_affected",
                "title": "Ice Affected",
                "guidance": (
                    "Provide dates for periods when recorded gage heights are affected by ice."
                ),
            },
            {
                "key": "edits",
                "title": "Edits",
                "guidance": (
                    "Discuss all edits to the recorded gage heights, including reasoning for the "
                    "erroneous values and methods used in making edits. Provide dates for any gaps "
                    "in recorded gage heights."
                ),
            },
            {
                "key": "gage_height_corrections",
                "title": "Gage-Height Corrections",
                "guidance": (
                    "Clearly describe the reasoning and timing for any gage height corrections. "
                    "Blanket statements for small instrument drift (< 0.03 ft) can be provided. "
                    "Larger corrections need detailed discussion."
                ),
            },
            {
                "key": "other_corrections",
                "title": "Other Corrections",
                "guidance": (
                    "Provide the reasoning and application period for any flushing, purge, or drawdown "
                    "corrections. Provide detailed discussion on any other types of corrections that "
                    "were developed, their period of applicability, and why they were deemed necessary "
                    "for the analysis period."
                ),
            },
            {
                "key": "peak_stage",
                "title": "Peak Stage",
                "guidance": (
                    "Provide the maximum recorded peak stage value, and the independent peak stage value "
                    "(including assessed uncertainty and the type of independent peak stage device used). "
                    "Describe the verification procedure results and which peak stage value was determined "
                    "to be the valid maximum. Indicate how this peak relates to previous peaks observed "
                    "during the water year."
                ),
            },
            {
                "key": "stage_discharge_relation",
                "title": "Stage-Discharge Relation",
                "guidance": (
                    "Indicate rating(s) (by number) active for analysis period. Include information on "
                    "when the rating was initially activated and when it was created. Provide general "
                    "assessment of how measurements made during analysis period plot on the active "
                    "rating curve."
                ),
            },
            {
                "key": "discharge_measurements",
                "title": "Discharge Measurements and Control Conditions",
                "guidance": (
                    "Summarize the discharge measurements (including observations of zero flow) made "
                    "during the analysis period: number made, range of flow measured, and the hydraulic "
                    "controls in effect for each measurement. Document the condition of the hydraulic "
                    "control for each measurement or inspection. Identify any check measurements or "
                    "measurements marked as not used."
                ),
            },
            {
                "key": "shift_curves",
                "title": "Shift Curves",
                "guidance": (
                    "Discuss the form of all shift curves developed for the analysis period, including "
                    "selected merge and hinge gage heights. Relate the shift curves to the hydraulic "
                    "control and observed control conditions — what is presumed to have caused the "
                    "measurements to plot where they do with respect to the rating curve?"
                ),
            },
            {
                "key": "application_of_shifts",
                "title": "Application of Shift Curves",
                "guidance": (
                    "Describe how the developed shift curves were applied to the time series. Relate "
                    "the causes to the application. If multiple events occurred between measurements, "
                    "explain which event(s) were used to apply the shifts and why. Provide justification "
                    "whenever a shift is simply prorated from visit to visit."
                ),
            },
            {
                "key": "computed_discharge",
                "title": "Computed Discharge",
                "guidance": (
                    "State the quality (excellent, good, fair, poor) of the computed discharge record "
                    "for the analysis period and provide brief reasoning. State the range of flow "
                    "experienced (min and max) in relation to recent measurements. Include general "
                    "discussion of uncertainty incorporating the quality of the recorded gage height "
                    "and the stage-discharge relation."
                ),
            },
            {
                "key": "estimates",
                "title": "Estimates",
                "guidance": (
                    "Provide dates for estimated periods. Describe methods used in developing estimated "
                    "unit value discharges. Reference any supporting information that was used and "
                    "archived as part of the estimation process."
                ),
            },
            {
                "key": "hydrographic_comparison",
                "title": "Hydrographic Comparison",
                "guidance": (
                    "Required for all analysis periods unless comparable sites are not available; if "
                    "none are available, provide a statement to that effect. Document sites used for "
                    "comparison. Discuss how the comparison was done and document the results. When "
                    "did the site hydrographs compare favorably, when did they compare poorly and why?"
                ),
            },
            {
                "key": "peak_streamflow",
                "title": "Peak Streamflow",
                "guidance": (
                    "Provide the maximum computed peak streamflow value based upon the peak verification "
                    "results. Indicate how this peak streamflow value relates to previous peak "
                    "streamflows observed during the water year."
                ),
            },
            {
                "key": "extremes",
                "title": "Extremes for Water Year",
                "guidance": (
                    "If the analysis period closes out a water year, provide maximum instantaneous "
                    "discharge and corresponding gage height, minimum daily discharge, and peak gage "
                    "height (if not associated with maximum instantaneous discharge). Include any "
                    "needed qualification statements. Example: Maximum discharge, 3,250 ft3/s, May 2, "
                    "gage height, 12.25 ft. Minimum daily discharge, 101 ft3/s, Feb. 23."
                ),
            },
            {
                "key": "comments",
                "title": "Comments",
                "guidance": (
                    "Provide any pertinent remarks or comments for the analysis period that are not "
                    "contained in the above sections."
                ),
            },
        ],
    },
    {
        "id": "groundwater",
        "label": "Groundwater Analysis",
        "sections": [
            {
                "key": "extremes",
                "title": "Extreme for Period of Analysis/Period of Record",
                "guidance": (
                    "Optional. Provide the maximum and minimum measured values for this period. "
                    "State the period of record high and low for the site."
                ),
            },
            {
                "key": "water_level_fluctuations",
                "title": "Water-Level Fluctuations/Trends",
                "guidance": (
                    "Mandatory. State how the site water-level record is usually affected by "
                    "artificial stresses (pumping, etc), earth tides, or other effects. Describe "
                    "how the water level record during the analysis period fits into the site's trend."
                ),
            },
            {
                "key": "missing_data",
                "title": "Missing Data",
                "guidance": (
                    "Mandatory. Provide dates and reasons for any gaps in the record."
                ),
            },
            {
                "key": "measurements",
                "title": "Measurements",
                "guidance": (
                    "Mandatory. List the number and dates of water level measurements that were made "
                    "during the period and note any unusual circumstances about the measurements."
                ),
            },
            {
                "key": "datum_corrections",
                "title": "Datum Corrections",
                "guidance": (
                    "Mandatory if applicable. State if levels were run during the period and any "
                    "noteworthy particulars about the leveling. Describe any movements of the "
                    "measuring point (MP), land-surface datum (LSD), and reference marks (RMs) "
                    "at the well. Describe how the surveyed effects were applied to the data."
                ),
            },
            {
                "key": "water_level_corrections",
                "title": "Water-Level Corrections",
                "guidance": (
                    "Mandatory if applicable. Clearly describe corrections applied to the water "
                    "levels collected during the period, including measuring point corrections."
                ),
            },
            {
                "key": "hydrographic_comparison",
                "title": "Hydrographic Comparison",
                "guidance": (
                    "Mandatory if applicable. Provide sites used for hydrographic comparison. "
                    "Discuss how the comparison was done and document the results. Where did the "
                    "sites compare favorably, where did they compare poorly and why?"
                ),
            },
            {
                "key": "comments",
                "title": "Comments",
                "guidance": (
                    "Optional. Provide any pertinent remarks or comments for the record period "
                    "that are not contained in the above sections."
                ),
            },
            {
                "key": "special_notes",
                "title": "Special Notes",
                "guidance": (
                    "Optional. If the collection and maintenance of this record required any special "
                    "(non-routine) trips during this period, state the date and purpose."
                ),
            },
        ],
    },
    {
        "id": "precipitation",
        "label": "Precipitation Analysis",
        "sections": [
            {
                "key": "precipitation_record",
                "title": "Precipitation Record",
                "guidance": (
                    "Describe the completeness of the precipitation record for the period. Include "
                    "general discussion of periods with any problems (ice/snow or clogged funnel "
                    "periods, for example)."
                ),
            },
            {
                "key": "backup_data",
                "title": "Backup Data",
                "guidance": (
                    "Describe where the backup data came from, why there was a gap in the primary "
                    "time-series, and the period that contains the merged data."
                ),
            },
            {
                "key": "missing_data",
                "title": "Missing Data or Affected by Ice/Snow or Funnel Clog",
                "guidance": (
                    "Provide dates for periods when recorded precipitation is missing or was likely "
                    "affected by funnel clogging, or snow/ice."
                ),
            },
            {
                "key": "edits",
                "title": "Edits",
                "guidance": (
                    "Discuss all edits/deletions to the recorded data, including reasoning for the "
                    "erroneous values. Provide dates for any gaps in recorded rainfall values."
                ),
            },
            {
                "key": "corrections",
                "title": "Corrections",
                "guidance": (
                    "Clearly describe the reasoning and timing for any corrections. Factor "
                    "corrections (or any type of correction) are extremely rare and difficult to "
                    "support; justification must be clearly described."
                ),
            },
            {
                "key": "estimates",
                "title": "Estimates",
                "guidance": (
                    "Provide dates for estimated daily value periods (no instantaneous value "
                    "estimates except for short periods of no rainfall that are fully documented). "
                    "Describe methods used in developing estimated daily value gage precipitation "
                    "amounts."
                ),
            },
            {
                "key": "hyetographic_comparison",
                "title": "Hyetographic Comparison",
                "guidance": (
                    "Required for all analysis periods, including those with no missing record, "
                    "unless suitable comparison sites are not available. Identify all sites used "
                    "for comparison. If a suitable site is not available, state why (comparison "
                    "site too distant, destroyed, or other reason). Discuss how each comparison "
                    "was done and document the results. When did the site hyetographs compare "
                    "favorably; when did they compare poorly and why?"
                ),
            },
            {
                "key": "calibrations",
                "title": "Calibrations",
                "guidance": (
                    "Provide the number and dates of any instrument calibrations made during the "
                    "period. Summarize the results and actions taken following each calibration."
                ),
            },
            {
                "key": "comments",
                "title": "Comments",
                "guidance": (
                    "Provide any pertinent remarks or comments for the analysis period that are "
                    "not contained in the above sections, such as recommendations that might help "
                    "to remediate compromising site conditions."
                ),
            },
        ],
    },
]

REPORT_TYPES_BY_ID = {rt["id"]: rt for rt in REPORT_TYPES}

REPORT_TYPE_CHOICES = [(rt["id"], rt["label"]) for rt in REPORT_TYPES]

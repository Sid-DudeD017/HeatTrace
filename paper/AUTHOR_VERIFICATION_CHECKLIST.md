# HeatTrace Author-Verification Checklist

Before final journal submission, the human authors must confirm, complete, or approve the following items. Every item requires deliberate human verification.

---

## 1. Title, Authorship, and Metadata Placeholders

- [ ] **Working Title Confirmation**:
  - *Current Working Title*: `HeatTrace: A Historical Heatwave Dataset and Evaluation Benchmark for Sustainable Cloud Scheduling`
  - *Action*: Confirm the dataset-and-benchmark framing and title.
- [ ] **Author Names and Ordering**:
  - *Current Placeholder*: `\author*[1]{\fnm{[AUTHOR NAME(S)} \sur{--- CONFIRM]}}`
  - *Action*: Populate complete author list, given names, surnames, and order of authorship.
- [ ] **Affiliations and Institutional Addresses**:
  - *Current Placeholders*: `[DEPARTMENT --- CONFIRM]`, `[INSTITUTION --- CONFIRM]`, `[CITY --- CONFIRM]`, `[STATE --- CONFIRM]`, `[COUNTRY --- CONFIRM]`
  - *Action*: Provide exact department, university/institution, and mailing address.
- [ ] **Corresponding Author Email**:
  - *Current Placeholder*: `[CORRESPONDING AUTHOR EMAIL --- CONFIRM]`
  - *Action*: Confirm corresponding author email address.
- [ ] **Target Springer Journal**:
  - *Current State*: Not embedded in the manuscript; selection remains an author decision.
  - *Action*: Confirm the target journal (e.g., *Journal of Cloud Computing*, *Sustainable Computing: Informatics and Systems*, *Computing*, or *Cluster Computing*) and verify reference formatting requirements.

---

## 2. Declarations and Policy Statements

- [ ] **Funding Statement**:
  - *Current Placeholder*: `[AUTHOR TO CONFIRM]`
  - *Action*: Disclose all grant numbers, government funding agencies, university fellowships, or state that no external funding was received.
- [ ] **Conflict of Interest / Competing Interests**:
  - *Current Placeholder*: `[AUTHOR TO CONFIRM]`
  - *Action*: State explicitly whether any author has financial, consulting, or personal relationships that could be viewed as influencing the work.
- [ ] **Data and Artifact Availability Statement**:
  - *Current State*: The manuscript distinguishes repository artifacts from external-provider raw data.
  - *Action*: Confirm which derived datasets, model weights, and archives will remain available at submission and which provider terms constrain redistribution.
- [ ] **Public Repository Availability**:
  - *Current Remote*: `https://github.com/Sid-DudeD017/HeatTrace.git`
  - *Verification Result*: An unauthenticated request to `https://github.com/Sid-DudeD017/HeatTrace` returned HTTP 404 on 2026-11-20.
  - *Action*: Make the intended repository publicly accessible or provide an archival DOI, then replace the manuscript's verification warning. Do not submit while the URL is inaccessible to reviewers.
- [ ] **AI-Assisted Drafting Disclosure**:
  - *Action*: Verify institutional and journal guidelines regarding disclosure of AI-assisted drafting tools (e.g., Springer Nature AI policy requirements for declaration in Acknowledgments or Methods).

---

## 3. Scientific and Evidence Boundaries Confirmation

- [ ] **Confirmed Non-Claims**:
  - [x] Confirmed: Does not claim heatwaves generally cause physical data-center outages.
  - [x] Confirmed: Does not claim reproduction of Ruparel's formal DRO, CVaR, Wasserstein, or battery frameworks.
  - [x] Confirmed: Does not claim HeatGuard superiority or formal coverage guarantees.
  - [x] Confirmed: Does not claim TinyLSTM causally drove scheduling benefits (H4 classified non-estimable).
  - [x] Confirmed: Does not claim strict ranking reversals occurred in the confirmatory evaluation (zero observed).
  - [x] Confirmed: Does not equate CAISO LMP to retail tariffs or EIA carbon to marginal emissions.
  - [x] Confirmed: Acknowledges synthetic thermal model is a controlled sensitivity, not calibrated physics.
- [ ] **Reproduction Framing**:
  - [x] Confirmed: Framed as strong same-environment artifact reproducibility; not independent public-checkout reproduction.
- [ ] **Multi-Station Extension Status and Triage**:
  - [x] Confirmed: Forecast-aware multi-station conclusions are explicitly unvalidated after the scientific audit.
  - [x] Confirmed: Cross-station neural forecast transfer (3,960 compromised cells, 61.1%) fully disclosed.
  - [x] Confirmed: High-load equal-service attrition (0/22 valid trios at 2x and 3x) fully documented.
  - [x] Confirmed: Surviving narrow claim (static power-cap vulnerability, +8.08 h median) isolated and caveats stated.
- [ ] **Planned Global Expansion**:
  - [x] Confirmed: Described strictly in future tense; clearly labeled as unexecuted future work.

---

## 4. Final Submission Bundle Verification

- [ ] **Compiled PDF Inspection**:
  - [x] `paper/main.pdf` compiled successfully (14 pages total, exactly 12 body pages before references).
  - [x] References start on page 13 and occupy pages 13--14.
  - [x] Reader-facing internal development labels were removed from prose, headings, tables, and captions.
- [ ] **Flat Submission Bundle**:
  - [x] Complete self-contained source bundle prepared in `paper/submission/`.
- [ ] **Institutional Sign-Off**:
  - [ ] Obtain final approval from all co-authors and department supervisors prior to journal submission.

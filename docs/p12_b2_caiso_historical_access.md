# Operational Record: CAISO Historical Data Access & Verification

**Document Status**: Operational Record (Track B2 Phase 2)  
**Creation Date**: 2026-10-31  
**Scope**: Direct verification and technical investigation of official CAISO historical data access mechanisms for Day-Ahead Market (DAM) Locational Marginal Prices (LMP).

---

## 1. Verified Official Endpoints & Observations

### 1.1 Programmatic OASIS API (v12)
- **Base URL**: `http://oasis.caiso.com/oasisapi/SingleZip` and `GroupZip`
- **Query / Product**: `queryname=PRC_LMP`, `market_run_id=DAM`, `version=12`, `resultformat=6`
- **Observed Behavior**:
  - Programmatic API requests for dates on or after **July 20, 2023** return valid zipped CSV datasets (`SUCCESS_DATA`).
  - Programmatic API requests for dates prior to **July 20, 2023** (including all of 2022 and June 1 – July 19, 2023) return an XML error document (`CAISO_ERROR_RESPONSE`):
    ```xml
    <m:OASISReport xmlns:m="http://www.caiso.com/soa/OASISReport_v1.xsd">
      <m:ERROR>
        <m:ERR_CODE>1000</m:ERR_CODE>
        <m:ERR_DESC>No data returned for the specified selection</m:ERR_DESC>
      </m:ERROR>
    </m:OASISReport>
    ```
- **Finding**: The public automated CAISO OASIS API enforces a rolling **39-month** data availability window. Older historical intervals are not served programmatically via unauthenticated SingleZip or GroupZip queries.

### 1.2 Web-Based MRI-OASIS Portal
- **HTTP URL**: `http://oasis.caiso.com/mrioasis/logon.do` (HTTP 302 redirect to HTTPS)
- **HTTPS URL**: `https://oasis.caiso.com/mrioasis/logon.do` (HTTP 200 OK)
- **Web Interface Verification**:
  - Direct HTTP inspection of `https://oasis.caiso.com/mrioasis/logon.do` confirms the portal is active (Software Version 8.2.1, Copyright California ISO).
  - The portal features standard Dojo/WebSDK menu structures:
    - `oasisMenu.Prices.EnergyPrices.LMP` (Day-Ahead and Real-Time LMP query interface)
    - `oasisMenu.Atlas`
    - `oasisMenu.SupportContact`
- **Operational Reality & Caveat**:
  - In an unauthenticated session, navigating and submitting historical batch download requests requires interactive browser session state, JavaScript runtime execution (Dojo Toolkit 1.17.2), session cookies (`JSESSIONID`, `BIGipServerprod-oasisui-int`, `TS01*`), and potentially user registration.
  - While the web portal serves the `oasisMenu.Prices.EnergyPrices.LMP` UI, downloading bulk archives spanning entire multi-month warm seasons (e.g. June 1 – October 1, 2022) via the interactive GUI is subject to web portal query size limits or may require CAISO Market Participant / client portal access.

---

## 2. Direct Verification vs. Inferred Route

To prevent assumptions and maintain documentation integrity:

> **Historical Note on Public OASIS API**:
> The public automated OASIS API systematically returned `ERR_CODE 1000` for dates prior to July 20, 2023 due to the 39-month rolling limit. Programmatic automated access alone could not recover 2022 or early 2023 data. Human export via the official Historical OASIS Data Downloader was required and has now been completed.

Specifically:
- **Directly Verified API Horizon**:
  1. The automated SingleZip and GroupZip endpoints fail with `ERR_CODE 1000` for all dates prior to July 20, 2023.
  2. The MRI-OASIS web portal at `https://oasis.caiso.com/mrioasis/logon.do` is online and serves the OASIS user interface.
  3. The menu hierarchy includes `oasisMenu.Prices.EnergyPrices.LMP`.
- **Completed Manual Acquisition Route**:
  1. The human researcher accessed the official Historical OASIS Data Downloader and retrieved the complete official daily multi-node group archives.
  2. The downloaded archives were placed into `data/v2/raw/caiso/bulk_historical/` and verified against the CAISO DAM LMP schema.

---

## 3. Option B Manual Recovery Completion Record

**Completion Date**: 2026-10-31  
**Status**: COMPLETE (Verified & Audited)

The human researcher completed the manual acquisition of official historical CAISO Day-Ahead Market (DAM) Locational Marginal Price (LMP) data for all missing warm-season intervals.

### 3.1 Inventory of Recovered Official Archives
- **Total Official Daily Archives**: 147 valid ZIP archives obtained via the Historical OASIS Data Downloader:
  - **2022 Season**: 98 recovered dates (`2022-06-01` to `2022-06-17`, `2022-06-26` to `2022-09-02`, `2022-09-11` to `2022-09-19`, `2022-09-28` to `2022-09-30`).
  - **2023 Season**: 49 recovered dates (`2023-06-01` to `2023-07-19`).
- **Archive Structure**:
  - Each daily archive is an official CAISO multi-node group ZIP package (`*_DAM_LMP_GRP_N_N_v12_csv.zip`).
  - Each contains CSV members for LMP, MCE, MCC, and MCL components.
  - Per protocol rules, only total LMP rows are parsed and used:
    - `MARKET_RUN_ID = DAM`
    - `LMP_TYPE = LMP`
    - `XML_DATA_ITEM = LMP_PRC`
  - Components `MCE`, `MCC`, and `MCL` are excluded.

### 3.2 Granular Verification & Invariants
- **Recovered Records per Declared Hub**:
  - `TH_NP15_GEN-APND`: 3,528 unique hourly intervals (2,352 for 2022; 1,176 for 2023).
  - `TH_ZP26_GEN-APND`: 3,528 unique hourly intervals (2,352 for 2022; 1,176 for 2023).
  - `TH_SP15_GEN-APND`: 3,528 unique hourly intervals (2,352 for 2022; 1,176 for 2023).
- **Daily Invariant**: Exactly 24 hourly records per downloaded day per hub.
- **Timestamp Invariant**: 0 duplicate timestamps.
- **Price Invariant**: 0 conflicting price values.
- **Error Response Handling**: The four pre-existing top-level `attempt_*.zip` files remain documented CAISO error responses (`ERR_CODE 1000`) and contribute zero observations.

### 3.3 Post-Recovery Full Season Coverage
Combining the recovered 147 daily archives with existing valid seasonal archives yields complete warm-season (June 1 00:00 to October 1 00:00 PDT = 2,928 UTC intervals) coverage:
- **TH_NP15_GEN-APND**: 2022 = 2,928/2,928 (PASS), 2023 = 2,928/2,928 (PASS).
- **TH_ZP26_GEN-APND**: 2022 = 2,928/2,928 (PASS), 2023 = 2,928/2,928 (PASS).
- **TH_SP15_GEN-APND**: 2022 = 2,928/2,928 (PASS), 2023 = 2,928/2,928 (PASS).
- **Post-Recovery Gap Inventory**: 0 remaining CAISO missing intervals across all 15 hub-years (2022–2026).

---

## 4. Official Support & Inquiry Contacts

If portal queries for 2022 or early 2023 cannot be exported directly through the web interface, the following official CAISO channels apply:
- **CAISO Client Services / Support**: `https://www.caiso.com` -> Support Contact
- **OASIS Support Desk**: Available through the portal footer link `parent.displayCallUp('oasisMenu.SupportContact','0')`.
- **Inquiry Submission**: Request official historical CSV exports for `DAM LMP_PRC` for hubs `TH_NP15_GEN-APND`, `TH_ZP26_GEN-APND`, and `TH_SP15_GEN-APND` covering:
  - Season 2022: `2022-06-01 07:00:00 UTC` to `2022-10-01 07:00:00 UTC`
  - Season 2023 (missing segment): `2023-06-01 07:00:00 UTC` to `2023-07-20 07:00:00 UTC`

# Weather event data workflow

## Source register and licensing

| Dataset | Role | License/access | Local raw location |
|---|---|---|---|
| [Hierarchical Disaster Tweet Classification Corpus (India + Nepal), Mendeley Data v1](https://data.mendeley.com/datasets/psv6b4zy9f/1), DOI [10.17632/psv6b4zy9f.1](https://doi.org/10.17632/psv6b4zy9f.1) | Supervised social-text classification: disaster/non-disaster and non-disaster/flood/earthquake labels | CC BY 4.0; cite creator Ujjwal Sinha, the dataset DOI, and transformations | `raw/social/disaster_tweets.zip`; extracted originals in `raw/social/source_files/dataset/` |
| [India Flood Inventory-Impacts (IFI-Impacts), Zenodo record 16994648](https://zenodo.org/records/16994648), DOI [10.5281/zenodo.16994648](https://doi.org/10.5281/zenodo.16994648) | Historical flood-event evidence, 1967–2023; **not** social-text training labels or proof for a current report | CC BY-NC 4.0 according to the published Zenodo record; non-commercial use only and attribution required | `raw/flood/` |
| [India rainfall catalog, Government of India OGD](https://www.data.gov.in/catalog/rainfall-india) | Separate historical rainfall evidence | Follow the terms of each selected OGD resource | `raw/rainfall/` (resource file not yet downloaded) |
| [Open-Meteo Forecast API](https://open-meteo.com/en/docs) | Current weather at eight configured city points; observations are persisted separately from reports | Follow Open-Meteo terms and attribution requirements | Live API response; raw provider payloads are not archived |
| [NASA POWER Daily API](https://power.larc.nasa.gov/docs/tutorials/service-data-request/api/) | Daily gridded temperature, precipitation, humidity, and wind for a selected point and date range | Public API; retain NASA POWER attribution, parameters, units, and retrieval time; respect service request limits | On-demand response; normalized daily rows are persisted in PostgreSQL |
| [USGS FDSN Event Web Service](https://earthquake.usgs.gov/fdsnws/event/1/) | Past-24-hour GeoJSON query in the India coordinate bounds, filtered by minimum magnitude | Public API; retain event ID, event URL, origin time, retrieval time, and USGS attribution | Live API response; normalized events are persisted in PostgreSQL |
| [IMD Public API Reference](https://api.imd.gov.in/public/api_reference.html) | District-wise rainfall endpoint researched during integration | API key required by endpoint; follow IMD access and use terms | Research-only; deliberately not integrated into this application |

The Mendeley archive contains multiple original CSVs, not one canonical
`disaster_tweets.csv`. The current training pipeline reads only
`TweetMasterData.csv`, `INDIANTWEETMASTER.csv`,
`TWEETDATASET( CLASS 0,1 AND 2).csv`, and `INDIANTWEETDATASET.csv`.
Those four extracted inputs are needed to regenerate the classifier training
data; download the CC BY 4.0 archive from the Mendeley record above and extract
the originals under `raw/social/source_files/dataset/` if they are not present.
The ZIP itself and other original CSVs are retained locally but are not
committed because the current pipeline does not consume them. The archive
SHA-256 is
`17f7ee65d3f7b1151cc4affdc1527d5d598725ba01b3d0f955c5440dd39f501d`.
Zenodo's current record lists the following original files (the listed MD5s
were checked against the downloaded files):

- `India_Flood_Inventory_v3.csv` — `fea75a9ff9eba8fb328eaddfacd21d67`
- `District_FloodImpact.csv` — `231d4157f462ea6c9bfd728c9dfbf520`
- `District_FloodedArea.csv` — `52744304c21f28b841fb3a28e510e789`
- `DFSI.csv` — `d15cbab2f15c3a6c393fd45220665211`

The 2025 Zenodo record's current license is **CC BY-NC 4.0**, even though older
copies or summaries may describe a different license. Check the upstream
record's license before redistributing or using its files commercially.

Only `raw/flood/India_Flood_Inventory_v3.csv` is currently read by the
preprocessing pipeline. The other three flood inventory exports listed above
are retained locally but are not committed because the current pipeline does
not consume them. The Government OGD catalog returned “No Result Found” during this integration
attempt, so no specific resource ID or downloadable CSV could be verified.
No placeholder or fabricated `rainfall_india.csv` is included. An unauthenticated
IMD request returned `API key missing`; IMD was therefore left out of the
runtime rather than presenting an unavailable API as live data. Open-Meteo city
conditions, NASA POWER daily point data, and USGS earthquakes are fetched by
the backend and stored in separate PostgreSQL tables. API responses retain their own
observation/event date, source, and retrieval time. NASA POWER is gridded daily
context and can include unavailable near-real-time dates; its documented fill
value is normalized to `null`. None of these source records automatically
verifies a citizen report.

## Processing and common schema

Never edit or overwrite files in `raw/`. Run:

```powershell
python datasets/clean_data.py
```

The cleaner validates expected source columns and label values, normalizes
whitespace, removes empty text, deduplicates identical text, and excludes
examples with conflicting labels. It keeps missing dates/geography blank
rather than guessing them. The flood inventory's original cause/description
fields are retained as processed text.

Generated files in `processed/` use the common columns:

```text
report_id,text,event_type,location,state,latitude,longitude,date,source,label,dataset_type
```

`weather_events.csv` combines source rows for exploration. For model training,
keep these separate:

- `social_disaster.csv`: Mendeley Task 1, `disaster` vs `non_disaster`.
- `social_event_type.csv`: Mendeley Task 2, `Flood`, `Earthquake`, and
  `non_disaster`.
- `historical_flood_evidence` rows: historical flood records only. They do
  not become positive/negative social-text examples.

The corpus's Task 1 files do not supply a particular hazard for every positive
tweet; such rows stay `Unclassified`. Task 2 labels only flood and earthquake.
Neither dataset supports inferring rainfall, heatwave, fog, or wind labels.

## Train/test split and model evaluation

The cleaner writes deterministic, class-stratified 80/10/10 train/validation/
test files with random seed 42. Then train and evaluate TF-IDF/logistic
regression models:

```powershell
python datasets/train_models.py
```

Artifacts and holdout metrics are written to `models/`. Do not load model files
from untrusted sources. Check test-set precision, recall, F1, confusion matrix,
and geographic/domain limitations before a deployment decision.

The current local random split (scikit-learn 1.9.1, seed 42) yielded 0.890
binary disaster-detection accuracy on 5,028 held-out rows and 0.961 event-label
accuracy on 2,648 held-out rows. Because the tweet IDs identify India and Nepal
source subsets, training also evaluates leave-one-region-out in both
directions. The latest regional results were:

| Task | Train Nepal → test India | Train India → test Nepal |
|---|---:|---:|
| Disaster detection | accuracy 0.832; macro F1 0.832 (16,998 rows) | accuracy 0.592; macro F1 0.519 (33,280 rows) |
| Event type | accuracy 0.705; macro F1 0.692 (13,600 rows) | accuracy 0.673; macro F1 0.653 (12,871 rows) |

The weak Nepal holdout on disaster detection includes only 0.235 recall for
`non_disaster`; event-type flood recall is 0.461 on the India holdout.
These differences are evidence of source/domain shift, not evidence the model
is suitable for operational decisions. Regional per-class precision/recall/F1
and confusion matrices are in
`models/*_regional_evaluation.json`, also embedded in each task's full
evaluation JSON.

Temporal evaluation is unavailable: the source tweet records used here do not
provide a usable event-date field. The cleaner leaves those dates blank rather
than inventing them. Neither random nor region-held-out corpus metrics are
real-world report verification results.

## What model output means

The text model can identify patterns similar to labelled social-media examples.
It **cannot** establish that a citizen report is true, current, in the stated
location, or supported by an official observation. Flood/earthquake text-model
labels are not evidence that an event happened. Keep ML classification,
external evidence, duplicate/suspicion signals, and report status as separate
fields. This project does not provide a report moderation or status-update
interface; new citizen reports remain in `Review`.
Displayed model scores are raw `predict_proba` outputs and have not been
calibrated; they must not be interpreted as event-verification probabilities.

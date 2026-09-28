# India–Nepal Hierarchical Disaster Tweet Corpus

**Title:** Hierarchical Disaster Tweet Classification Corpus (India + Nepal)

**Short name:** `INDIA-NEPAL-DISASTER-TWEETS`

**Description:** A multi-stage disaster-informatics corpus of X (Twitter) posts for (1) disaster vs non-disaster detection, (2) disaster-type classification (flood vs earthquake), and (3) fine-grained humanitarian-support labelling. It pairs the original CrisisNLP / CrisisLex Nepal–flood collections used in the paper with a matched **India** collection covering all 28 states and 8 union territories. Tweets are stored as noisy, lowercased social-media text (missing punctuation, `andamp`, `multi stop`), in the same style as CrisisLex.

**Tasks (paper cascade)**

| Stage | Task | Labels |
|---|---|---|
| Task 1 | Disaster vs non-disaster | `0` non-disaster, `1` disaster |
| Task 2 | Disaster type | `0` non-disaster, `1` flood, `2` earthquake |
| Task 3 | Humanitarian support (disaster tweets only) | 5 `Help` classes |

**Suggested split:** 80% train / 20% test, stratified by `Target` (and by `Help` on Task 3). Paper seeds: 42, 52, 62.

**Help classes (Task 3)**

| `Help` | Meaning |
|---|---|
| Other useful information | Updates, helplines, official bulletins, aftershock / flood alerts |
| Donations and volunteering | Relief, NDRF/Army, blood camps, volunteer calls |
| Sympathy and support | Prayers, condolences, solidarity |
| Food and Medicine | Casualties, hospitals, water, ration, medical need |
| Infrastructure and utilities | Roads, airports, power, buildings, bridges |

---

## Files

### Original paper collections (Nepal / CrisisLex)

#### 1. `TweetMasterData.csv` — Task 1

| Field | Type | Description |
|---|---|---|
| `Tweet_id` | string | Tweet identifier |
| `Target` | int | `0` non-disaster, `1` disaster |
| `Tweet_text` | string | Tweet body |

- **Rows:** 33,369  
- **Labels:** non-disaster 14,417 · disaster 18,952  
- **Use:** Binary disaster detection (Table 9 in the paper).

#### 2. `TWEETDATASET( CLASS 0,1 AND 2).csv` — Task 2

| Field | Type | Description |
|---|---|---|
| `Tweet_id` | string | Tweet identifier |
| `Target` | int | `0` non-disaster, `1` flood, `2` earthquake |
| `Tweet_text` | string | Tweet body |

- **Rows:** 15,435  
- **Labels:** non-disaster 4,783 · flood 4,873 · earthquake 5,779  
- **Use:** Disaster-type classification (Table 10). Earthquake tweets feed Task 3.

#### 3. `NEPALEARTHQUAKE.csv` — Task 3 (Nepal earthquake)

| Field | Type | Description |
|---|---|---|
| `Tweet_id` | string | Tweet identifier |
| `Tweet_text` | string | Tweet body |
| `Target` | int | Always `2` (earthquake) |
| `Help` | string | One of the five humanitarian classes |

- **Rows:** 5,778 (all earthquake)  
- **Help mix:** Other useful information 2,584 · Donations and volunteering 1,073 · Sympathy and support 1,021 · Food and Medicine 752 · Infrastructure and utilities 348  
- **Use:** Fine-grained humanitarian labelling on Nepal earthquake tweets (Table 12).

---

### India collections (all 28 states + 8 UTs)

#### 4. `INDIANTWEETMASTER.csv` — Task 1 (India)

Same schema as `TweetMasterData.csv`.

- **Rows:** 17,000  
- **Labels:** `0` non-disaster 7,200 · `1` disaster 9,800  
- **Content:** Everyday Indian posts (cricket, food, travel, exams) vs flood/earthquake reports from Indian cities.  
- **Use:** Train or test Task 1 on India; domain-shift vs `TweetMasterData.csv`.

#### 5. `INDIANTWEETDATASET.csv` — Task 2 (India)

Same schema as `TWEETDATASET( CLASS 0,1 AND 2).csv`.

- **Rows:** 13,600  
- **Labels:** `0` non-disaster 4,200 · `1` flood 4,300 · `2` earthquake 5,100  
- **Use:** Train or test disaster-type classification on India; transfer from the CrisisLex type file.

#### 6. `INDIANEARTHQUAKE.csv` — Task 3 (India earthquake)

| Field | Type | Description |
|---|---|---|
| `Tweet_id` | string | Tweet identifier |
| `Tweet_text` | string | Tweet body |
| `Target` | int | Always `2` (earthquake) |
| `Help` | string | Five humanitarian classes (same names as Nepal) |
| `State` | string | Indian state or union territory (36 unique) |
| `City` | string | City / district mentioned |
| `Seismic_zone` | string | BIS zone `II` / `III` / `IV` / `V` |

- **Rows:** 9,200  
- **Geography:** All 28 states and 8 UTs. Himalaya, North-East, Gujarat, and Delhi have higher volume (Zone IV–V). Distant states appear mainly as felt-tremor, donation, and family-contact tweets.  
- **Use:** India analogue of `NEPALEARTHQUAKE.csv`; state-wise tables; Nepal → India transfer.

#### 7. `INDIANFLOOD.csv` — Task 3 (India flood)

Same columns as `INDIANEARTHQUAKE.csv`.

- **Rows:** 7,200  
- **`Target`:** Always `1` (flood)  
- **Geography:** All 36 states/UTs; extra weight on Assam, Bihar, Kerala, West Bengal, Odisha, Maharashtra, Tamil Nadu.  
- **Use:** Humanitarian labelling for Indian floods (Kosi, Brahmaputra, Kerala monsoon, Chennai / Mumbai waterlogging).

---

## How the files connect

```
Task 1  disaster vs not     TweetMasterData.csv
                            INDIANTWEETMASTER.csv
                              │
                              ▼  if disaster
Task 2  flood / earthquake  TWEETDATASET( CLASS 0,1 AND 2).csv
                            INDIANTWEETDATASET.csv
                              │
              ┌───────────────┴───────────────┐
              ▼                               ▼
Task 3     flood help                    earthquake help
        INDIANFLOOD.csv               NEPALEARTHQUAKE.csv
        Target = 1                    INDIANEARTHQUAKE.csv
                                      Target = 2
```


---


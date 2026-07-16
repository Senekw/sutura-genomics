# Sutura - real interactive sessions (local llama3.2:3b, no API key)

The user cd's into their data folder and types `sutura`. No flags, no paths - they talk in plain language and watch it work.

## Session 1 - bare intent, uses the current folder

The user is *in* their data folder, so no path is needed - Sutura uses the current directory automatically.

```text
~$ cd C:\Users\karti\AppData\Local\Temp\claude\C--Users-karti-arca\e41297fd-7708-4246-8c89-eab3771d3bc1\scratchpad\demo_data
~$ sutura

you> align these sections and reconstruct in 3D
      (info) no folder given — using the current directory (C:\Users\karti\AppData\Local\Temp\claude\C--Users-karti-arca\e41297fd-7708-4246-8c89-eab3771d3bc1\scratchpad\demo_data)
  On it: load sections -> QC -> routing -> align each pair -> post-QC -> 3D reconstruct -> report. Everything runs locally; the model only sees metadata.
  > Load data - scanning C:\Users\karti\AppData\Local\Temp\claude\C--Users-karti-arca\e41297fd-7708-4246-8c89-eab3771d3bc1\scratchpad\demo_data
      ... reading DLPFC_151508 (h5ad) (50%)
  [v] 2 section(s): DLPFC_151507 (4226 spots), DLPFC_151508 (4384 spots)
  > Quality control - validating inputs
      ... QC DLPFC_151508 (50%)
  [v] 2/2 passed
  > Distribution check - DLPFC_151507 vs DLPFC_151508
      route -> Sutura (graph model) (in-distribution; maha 0.85, overlap 100%)
  [v] route -> Sutura (graph model) (Mahalanobis 0.85, gene overlap 100%)
  > Align - DLPFC_151507 -> DLPFC_151508 (auto-routed orchestrator)
      ... aligning with Sutura graph model (45%)
      ... writing aligned output (92%)
      ... done (100%)
  [v] Sutura - 1.29 spot-pitch median error (measured error)
  > Post-alignment QC - DLPFC_151507 -> DLPFC_151508
  [v] pass: median error 1.29 spot-pitch
  > 3D reconstruction - stacking aligned sections
  [v] 2 sections, 8610 points
  > Generate report - summarising results
  [v] report.md (34 lines)
  * bundle: C:\Users\karti\AppData\Local\Temp\claude\C--Users-karti-arca\e41297fd-7708-4246-8c89-eab3771d3bc1\scratchpad\interactive_home\results\job-20260716-162649-8347d6
      [turn 44.1s]

you> how well did it align?
  Metrics for job job-20260716-162649-8347d6 (1 pair(s)):
    - DLPFC_151507 -> DLPFC_151508: Sutura | 1.29 spot-pitch median error (measured vs ground truth) | post-QC: pass
      [turn 7.7s]

you> which section aligned worst?
  Worst-aligned pair: DLPFC_151507 -> DLPFC_151508 (Sutura, 1.29 spot-pitch median error (measured vs ground truth)).
      [turn 3.3s]
```

## Session 2 - conversational: asks where the data is

Started from an empty folder. Sutura asks where the data is instead of erroring; the user just pastes the folder and it runs.

```text
~$ cd C:\Users\karti\AppData\Local\Temp\claude\C--Users-karti-arca\e41297fd-7708-4246-8c89-eab3771d3bc1\scratchpad\empty_folder
~$ sutura

you> align these sections and reconstruct in 3D
  I don't see any spatial sections in this folder (C:\Users\karti\AppData\Local\Temp\claude\C--Users-karti-arca\e41297fd-7708-4246-8c89-eab3771d3bc1\scratchpad\empty_folder).
  Where are your data files? Tell me the folder (e.g. C:\path\to\data), or cd into it and ask again. I read .h5ad, Space Ranger, or Xenium output.
      [turn 4.0s]

you> C:\Users\karti\AppData\Local\Temp\claude\C--Users-karti-arca\e41297fd-7708-4246-8c89-eab3771d3bc1\scratchpad\demo_data
  On it: load sections -> QC -> routing -> align each pair -> post-QC -> 3D reconstruct -> report. Everything runs locally; the model only sees metadata.
  > Load data - scanning C:\Users\karti\AppData\Local\Temp\claude\C--Users-karti-arca\e41297fd-7708-4246-8c89-eab3771d3bc1\scratchpad\demo_data
      ... reading DLPFC_151508 (h5ad) (50%)
  [v] 2 section(s): DLPFC_151507 (4226 spots), DLPFC_151508 (4384 spots)
  > Quality control - validating inputs
      ... QC DLPFC_151508 (50%)
  [v] 2/2 passed
  > Distribution check - DLPFC_151507 vs DLPFC_151508
      route -> Sutura (graph model) (in-distribution; maha 0.85, overlap 100%)
  [v] route -> Sutura (graph model) (Mahalanobis 0.85, gene overlap 100%)
  > Align - DLPFC_151507 -> DLPFC_151508 (auto-routed orchestrator)
      ... aligning with Sutura graph model (45%)
      ... writing aligned output (92%)
      ... done (100%)
  [v] Sutura - 1.29 spot-pitch median error (measured error)
  > Post-alignment QC - DLPFC_151507 -> DLPFC_151508
  [v] pass: median error 1.29 spot-pitch
  > 3D reconstruction - stacking aligned sections
  [v] 2 sections, 8610 points
  > Generate report - summarising results
  [v] report.md (34 lines)
  * bundle: C:\Users\karti\AppData\Local\Temp\claude\C--Users-karti-arca\e41297fd-7708-4246-8c89-eab3771d3bc1\scratchpad\interactive_home\results\job-20260716-162742-de6fd9
      [turn 32.5s]

you> which method did you use, and why?
  Routing decisions (why each method was chosen):
    - DLPFC_151507 -> DLPFC_151508: routed to Sutura because it is in-distribution for the pretrained Sutura model (Mahalanobis 0.85 < 2.5); the graph model is most accurate here, so Sutura was used.
      [turn 7.6s]
```

# Test confusion — Nivas 200

Mapping: Silent=0, Speak=1.
TN = gold SILENT pred SILENT. FP = gold SILENT pred SPEAK.
FN = gold SPEAK pred SILENT. TP = gold SPEAK pred SPEAK.

| method | n | macro-F1 | speak-F1 | silent-F1 | speak rate | TN | FP | FN | TP |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| LoRA_best | 200 | 0.8776 | 0.8605 | 0.8947 | 0.4100 | 102 | 8 | 16 | 74 |
| B1_always_silent | 200 | 0.3548 | 0.0000 | 0.7097 | 0.0000 | 110 | 0 | 90 | 0 |
| B2_question | 200 | 0.6821 | 0.6519 | 0.7123 | 0.4550 | 78 | 32 | 31 | 59 |
| B3_no_helper_and_question | 200 | 0.7748 | 0.7162 | 0.8333 | 0.2900 | 105 | 5 | 37 | 53 |

LoRA vs B3: macro-F1 0.8776 vs 0.7748. LoRA ≥ B3.

best_adapter_macro_f1=0.8776
base=Qwen/Qwen2.5-7B-Instruct rev=a09a35458c702b33eeacc393d103063234e8bc28 train=sft_train_1to3.jsonl

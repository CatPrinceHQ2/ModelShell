# Model-data attribution

The bundled 3,143,280-parameter base checkpoint (counting its tied input/output embedding once) was trained from the project’s scrubbed subset of **Shell Commands Used by Participants of Hands-on Cybersecurity Training**, Zenodo record [6670113](https://zenodo.org/records/6670113), version 3. The record lists the dataset as CC BY 4.0. The training corpus is cybersecurity-lab shell history and may not represent ordinary terminal work. Bash history suggestions are enabled by default and can be disabled with `MODELSHELL_HISTORY_CONTEXT=0`; ModelShell reads a bounded tail of the active Bash HISTFILE into session memory. See README for privacy details.

The bundled pairwise reranker was fit from local candidate ratings. It is separate from the language-model checkpoint and does not include the model used to produce those ratings.

The preference reranker and frequency tables are separate generated artifacts. No Qwen model is bundled; it was used only to provide local candidate ratings for the reranker.

The supplied project does not establish a license for the source code. Add a code license before public redistribution. Dataset attribution and terms do not by themselves grant a license to the code or all generated artifacts.

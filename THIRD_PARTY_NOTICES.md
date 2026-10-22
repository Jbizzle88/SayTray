# Third-party notices

SayTray plays speech with Piper and optional voice models downloaded at install time or from the in-app voice list. This file is the attribution and license notice for those pieces. It is not legal advice.

SayTray's own code is MIT; see [LICENSE](LICENSE).

## Piper (piper-tts 1.8.0)

- **License:** GPL-3.0-or-later
- **Project:** https://github.com/OHF-voice/piper1-gpl
- **Source for the version SayTray installs:** https://github.com/OHF-voice/piper1-gpl/tree/v1.8.0
- **License text:** https://www.gnu.org/licenses/gpl-3.0.html
- **Package:** https://pypi.org/project/piper-tts/1.8.0/

SayTray does not modify Piper. macOS runs it in a separate helper process (`saytray_piper.py`). Windows imports it in the tray app's Python process. Selling a build that includes GPL code is allowed; buyers must receive this notice and can obtain the corresponding source from the links above. A paid build cannot add extra restrictions on the GPL-covered work.

## espeak-ng

- **License:** GPL-3.0-or-later (GNU General Public License version 3)
- **Project:** https://github.com/espeak-ng/espeak-ng
- **License text:** https://github.com/espeak-ng/espeak-ng/blob/master/COPYING

Piper uses espeak-ng to turn text into phonemes. espeak-ng is installed as part of the piper-tts package.

## Voice models

The voices below are the only ones SayTray installs or offers for download. They were trained from scratch, or fine-tuned only from public-domain models, on public-domain or CC BY data. SayTray does not ship or offer Ryan (CC BY-NC-SA), Lessac (Blizzard 2013 research-only), Amy, or LibriTTS-R (fine-tuned from Lessac).

Model cards for the Hugging Face voices: https://huggingface.co/rhasspy/piper-voices

### Installed by default (~170 MB)

| Voice | What you hear | Dataset and license |
| --- | --- | --- |
| **Norman (medium)** `en_US-norman-medium` | Male, US. Default voice. | LibriVox recordings, public domain. Trained from scratch by Bryce Beattie. [Model card](https://huggingface.co/rhasspy/piper-voices/blob/main/en/en_US/norman/medium/MODEL_CARD) |
| **LJSpeech (high)** `en_US-ljspeech-high` | Female, US. | [LJ Speech](https://keithito.com/LJ-Speech-Dataset/), public domain. Trained from scratch by Bryce Beattie. [Model card](https://huggingface.co/rhasspy/piper-voices/blob/main/en/en_US/ljspeech/high/MODEL_CARD) |

### Optional downloads (from Settings, or the Voice menu on Windows)

| Voice | What you hear | Dataset and license |
| --- | --- | --- |
| **Kristin (medium)** `en_US-kristin-medium` | Female, US. ~61 MB | LibriVox, public domain. Trained from scratch. [Model card](https://huggingface.co/rhasspy/piper-voices/blob/main/en/en_US/kristin/medium/MODEL_CARD) |
| **John (medium)** `en_US-john-medium` | Male, US. ~61 MB | LibriVox, public domain. Fine-tuned from Kristin (also public domain). [Model card](https://huggingface.co/rhasspy/piper-voices/blob/main/en/en_US/john/medium/MODEL_CARD) |
| **Cori (high)** `en_GB-cori-high` | Female, UK. ~109 MB | LibriVox, public domain. Trained from scratch. [Model card](https://huggingface.co/rhasspy/piper-voices/blob/main/en/en_GB/cori/high/MODEL_CARD) |
| **Bryce (medium)** `en_US-bryce-medium` | Male, US. ~61 MB | The author's own recordings, public domain. Fine-tuned from an unreleased recording of the same speaker. [Model card](https://huggingface.co/rhasspy/piper-voices/blob/main/en/en_US/bryce/medium/MODEL_CARD) |
| **LibriTTS (high)** `en_US-libritts-high` | Multi-speaker, US. ~130 MB. SayTray offers speaker ids 0 (female), 2 (male), and 4 (female). | LibriTTS, **CC BY 4.0**. Attribution is required; see below. Trained from scratch. [Model card](https://huggingface.co/rhasspy/piper-voices/blob/main/en/en_US/libritts/high/MODEL_CARD) |
| **Jenny (Dioco)** `jenny-dioco` | Female, Irish/UK. ~61 MB | From-scratch model by Bryce Beattie, not the Hugging Face `en_GB-jenny_dioco` model (that one was fine-tuned from Lessac and is not used). See the Jenny credit below. |

Bryce Beattie publishes his models at https://brycebeattie.com/files/tts/ and says: "Feel free to use these for any legal and ethical purpose."

## LibriTTS attribution (CC BY 4.0)

Required when the optional LibriTTS voice is used. The corpus is Creative Commons Attribution 4.0 International: https://creativecommons.org/licenses/by/4.0/

> Heiga Zen, Viet Dang, Rob Clark, Yu Zhang, Ron J. Weiss, Ye Jia, Zhifeng Chen, and Yonghui Wu, "LibriTTS: A Corpus Derived from LibriSpeech for Text-to-Speech," Interspeech 2019.
> https://www.openslr.org/60/ · https://arxiv.org/abs/1904.02882

LibriTTS is derived from the LibriSpeech materials at https://www.openslr.org/12/.

## Jenny (Dioco) credit

The optional voice must be named **Jenny (Dioco)** wherever SayTray lists it. That is the attribution required by the training dataset.

- **Dataset:** Jenny (dioco-group), https://github.com/dioco-group/jenny-tts-dataset — commercial use is allowed. Attribution means the voice is called "Jenny (Dioco)".
- **Model weights:** trained from scratch by Bryce Beattie, https://brycebeattie.com/files/tts/ (files `jenny.onnx` and `jenny.onnx.json`). The trainer's page says attribution is required, similar to CC BY, and that he imposes no further restrictions.

SayTray does not use `en_GB-jenny_dioco-medium` from the rhasspy/piper-voices Hugging Face repo.

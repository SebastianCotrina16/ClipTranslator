## 1.7.0

- **Ollama starts by itself:** if Ollama is closed, ClipTranslator opens it in the background when it needs to translate. No window, nothing to do.
- **Smart App Control:** the app now opens through the standard Python launcher, so Windows Smart App Control should no longer block it.
- If the translation model stops working during **Process all**, the batch stops with one clear message instead of failing every clip. What was already transcribed is kept.

## 1.6.0

- **Export all videos:** after Process all, click **Export all videos** to create the videos of every processed clip at once, with the same style.
- **Remembered fixes:** when you fix a word or a short phrase in a subtitle (like a misheard name), ClipTranslator remembers it and fixes it the same way in your next clips. See or remove them in **Remembered fixes**, under Names.
- **Done notifications:** when a clip, a batch or a video finishes while you are in another window, you hear a sound and get a Windows notification.
- **What's new:** this window. Open it again any time from the bottom-right corner.

## 1.5.5

- Clips that mix English with a lot of Hindi are detected on their own and translated straight to English.
- Lines that may be misheard are marked with "may be misheard: check it" so you know which ones to look at.

## 1.5.4

- Hindi clips are written straight in English by the speech model, which understands Hindi mixed with English much better.
- GevoArt is always spelled right.

## 1.5.3

- The installed version is shown in the bottom-right corner and in the window title.

## 1.5.2

- **Process all** transcribes every clip first and then translates them all, so each model loads only once and the batch finishes sooner.

## 1.5.1

- Translated prompts appear with the same fade-in as Gartic Phone, so the original text never flashes.

## 1.5.0

- **Translate the prompts on screen:** when exporting a video, the Gartic Phone album prompts can be translated on the video, with a wider box or a fit-in-box style.

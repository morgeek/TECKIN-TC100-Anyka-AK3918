  // --- SD card: the translated word "free" (settings.html #sd_free_word) for the size shown in Settings -> Recording
  function sdFreeWord() { var w = byId("sd_free_word"); return w ? w.textContent : "free"; }
  if (typeof window !== "undefined") window.tc100SdFreeWord = sdFreeWord;

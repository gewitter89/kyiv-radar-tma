/* Kyiv Radar iPhone uploads: progressive enhancement for native HEIC/HEIF.
   Browser-supported HEIC images are converted to JPEG without metadata.
   If the WebView cannot decode HEIC, return a clear error instead of
   silently uploading an unsupported file or weakening server validation. */
(() => {
  "use strict";
  const LIMIT = 24 * 1024 * 1024;
  const isHeic = file => /image\/hei[cf]/i.test(file.type || "") ||
      /\.(heic|heif)$/i.test(file.name || "");
  async function convertHeic(file) {
    if (file.size > LIMIT) throw new Error("HEIC-фото завелике для обробки на телефоні");
    const url = URL.createObjectURL(file);
    try {
      const img = document.createElement("img");
      img.decoding = "async";
      img.src = url;
      try {
        if (typeof img.decode === "function") await img.decode();
        else await new Promise((ok, fail) => { img.onload = ok; img.onerror = fail; });
      } catch (_) {
        throw new Error(
          "Цей браузер не може відкрити HEIC. На iPhone для нових фото оберіть Налаштування → Камера → Формати → Найбільш сумісний (JPG)."
        );
      }
      const originalWidth = img.naturalWidth, originalHeight = img.naturalHeight;
      if (!originalWidth || !originalHeight) throw new Error("HEIC-фото пошкоджене");
      const scale = Math.min(1, 2560 / Math.max(originalWidth, originalHeight));
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.round(originalWidth * scale));
      canvas.height = Math.max(1, Math.round(originalHeight * scale));
      const context = canvas.getContext("2d");
      if (!context) throw new Error("Не вдалося підготувати фото для відправлення");
      context.drawImage(img, 0, 0, canvas.width, canvas.height);
      const blob = await new Promise((ok,fail) => {
        canvas.toBlob(value => value ? ok(value) : fail(new Error("Помилка конвертації HEIC")), "image/jpeg", 0.82);
      });
      // Release canvas's pixel buffer before the next image.
      canvas.width = 1; canvas.height = 1;
      const name = String(file.name || "photo.heic").replace(/\.(heic|heif)$/i, "") + ".jpg";
      return new File([blob],name,{type:"image/jpeg",lastModified:Date.now()});
    } finally {
      URL.revokeObjectURL(url);
    }
  }
  window.krPrepareUploadPhotos = async function(files, updateStatus) {
    const prepared = [];
    for (const file of files) {
      if (isHeic(file)) {
        if (typeof updateStatus === "function") updateStatus("Конвертуємо HEIC у JPG…");
        prepared.push(await convertHeic(file));
      } else {
        prepared.push(file);
      }
    }
    return prepared;
  };
})();

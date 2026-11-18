/* Kyiv Radar: conservative client-side catalog hygiene.
   A flagged title is NOT proof that another value is correct.
   Never silently invent address, room count, metro, availability or verification. */
(() => {
  "use strict";
  const junk = /(?:грн\s*Додати\s*в\s*обране|Додати\s*в\s*обране)/iu;
  const stations = [
    "Позняки", "Дарниця", "Харківська", "Осокорки", "Чернігівська",
    "Шулявська", "Вокзальна", "Лівобережна", "Деміївська",
    "Васильківська", "Теремки", "Голосіївська", "Нивки",
    "Печерська", "Берестейська", "Іподром", "Мінська", "Оболонь"
  ];
  // We may inspect explicit counts inside *already permitted* source metadata.
  // Never infer room count from "studio", "окрема спальня" or a guessed floor.
  // This is an internal consistency check, NOT verification of a live OLX page.
  const numericRoomPattern = /(?:^|[^\p{L}\d])((?:1[0-5]|[1-9]))\s*(?:[-–‑]?\s*[хx]\s*)?[-–‑]?\s*(?:к(?![\p{L}\d])|кімн(?:ат\p{L}*)?\.?|комн(?:ат\p{L}*)?\.?)/giu;
  const lexicalRoomPatterns = [
    [1, /(?:^|[^\p{L}])(?:однокімнатн\p{L}*|однокомнатн\p{L}*|однушк\p{L}*)/iu],
    [2, /(?:^|[^\p{L}])(?:двокімнатн\p{L}*|двохкімнатн\p{L}*|двухкомнатн\p{L}*|двушк\p{L}*)/iu],
    [3, /(?:^|[^\p{L}])(?:трикімнатн\p{L}*|трьохкімнатн\p{L}*|трехкомнатн\p{L}*|трёхкомнатн\p{L}*)/iu],
    [4, /(?:^|[^\p{L}])(?:чотирикімнатн\p{L}*|чотирьохкімнатн\p{L}*|четырехкомнатн\p{L}*|четырёхкомнатн\p{L}*)/iu],
    [5, /(?:^|[^\p{L}])(?:пятикомнатн\p{L}*|п'ятикімнатн\p{L}*|п’ятикімнатн\p{L}*)/iu]
  ];
  function explicitRoomClaims(...parts) {
    const results = new Set();
    for (const part of parts) {
      if (typeof part !== 'string') continue;
      const text = part.slice(0, 8192).toLocaleLowerCase("uk-UA");
      for (const match of text.matchAll(numericRoomPattern)) results.add(Number(match[1]));
      for (const [count, pattern] of lexicalRoomPatterns) {
        if (pattern.test(text)) results.add(count);
      }
    }
    return [...results].sort((a,b) => a-b);
  }
  function roomCountFromTitle(title) {
    const claims = explicitRoomClaims(title);
    return claims.length === 1 ? claims[0] : null;
  }
  function countFromMetadata(value) {
    // Avoid treating "2x", "2 rooms?" or Boolean true as trusted metadata.
    if (typeof value === "number" && Number.isSafeInteger(value) && value >= 1 && value <= 100) return value;
    if (typeof value === "string" && /^[1-9]\d?$/u.test(value.trim())) return Number(value.trim());
    return null;
  }
  function titleMetro(title) {
    const text = String(title || "").toLocaleLowerCase("uk-UA");
    const hits = stations.filter(name => {
      const phrase = name.toLocaleLowerCase("uk-UA");
      return text.includes("метро " + phrase) ||
        text.includes("м." + phrase) ||
        text.includes("м. " + phrase) ||
        text.includes("біля м. " + phrase);
    });
    return hits.length === 1 ? hits[0] : null;
  }
  function scrub(list) {
    if (!Array.isArray(list)) return [];
    return list.filter(x => x && typeof x === "object").map(item => {
      const badAddress = item.addressConflict === true || junk.test(String(item.address || ""));
      const sourceClaims = explicitRoomClaims(item.title, item.desc);
      const structuredRooms = countFromMetadata(item.rooms);
      // Ownership verification does not override a contradiction in room data.
      const roomsConflict = item.roomConflict === true ||
        sourceClaims.length > 1 ||
        (structuredRooms !== null && sourceClaims.length === 1 &&
         sourceClaims[0] !== structuredRooms);
      // A model-derived station or walk time is not a sourced routing fact.
      // Imports with no independently verified location cannot assert either.
      const locationVerified = item.locationVerified === true && !badAddress;
      const source = String(item.source || "").toUpperCase();
      const importedUnverified = (source === "OLX" || source === "DOM.RIA") && !locationVerified;
      const titleStation = titleMetro(item.title);
      const metroConflict = !importedUnverified &&
        (item.metroConflict === true || (titleStation && item.metro &&
        !String(item.metro).toLocaleLowerCase("uk-UA")
          .includes(titleStation.toLocaleLowerCase("uk-UA")) &&
        item.isOwnerVerified !== true));
      return {
        ...item,
        // A masked number is not evidence that a real contact is available.
        phoneMasked: item.contactVerified === true ? item.phoneMasked || null : null,
        address: badAddress ? "Адреса уточнюється" : item.address,
        rooms: roomsConflict ? null : structuredRooms,
        metro: importedUnverified ? null : metroConflict ? "Метро уточнюється" : item.metro,
        walkMin: importedUnverified ? null : item.walkMin,
        roomConflict: Boolean(roomsConflict),
        metroConflict: Boolean(metroConflict),
        addressConflict: Boolean(badAddress),
        locationVerified
      };
    });
  }
  window.krQualityCatalog = scrub;
  window.krQualityRules = {roomCountFromTitle,explicitRoomClaims,countFromMetadata,titleMetro};
})();

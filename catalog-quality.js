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
  function roomCountFromTitle(title) {
    const text = String(title || "").toLocaleLowerCase("uk-UA");
    const results = new Set();
    const pattern = /(^|[^\d])([1-5])\s*(?:[-‑]\s*(?:х\s*)?)?(?:к(?![а-яіїєґa-z])|к(?=\s*кварт)|кімн|комн)/giu;
    for (const match of text.matchAll(pattern)) results.add(Number(match[2]));
    return results.size === 1 ? [...results][0] : null;
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
      const badAddress = junk.test(String(item.address || ""));
      const roomFromTitle = roomCountFromTitle(item.title);
      const roomsConflict = Number.isInteger(roomFromTitle) &&
        Number.isInteger(Number(item.rooms)) &&
        Number(item.rooms) > 0 && roomFromTitle !== Number(item.rooms) &&
        item.isOwnerVerified !== true;
      const titleStation = titleMetro(item.title);
      const metroConflict = titleStation &&
        !String(item.metro || "").toLocaleLowerCase("uk-UA")
          .includes(titleStation.toLocaleLowerCase("uk-UA")) &&
        item.isOwnerVerified !== true;
      // Only independently verified location may become a precise map marker.
      const locationVerified = item.locationVerified === true && !badAddress;
      return {
        ...item,
        address: badAddress ? "Адреса уточнюється" : item.address,
        rooms: roomsConflict ? null : item.rooms,
        metro: metroConflict ? "Метро уточнюється" : item.metro,
        roomConflict: Boolean(roomsConflict),
        metroConflict: Boolean(metroConflict),
        addressConflict: Boolean(badAddress),
        locationVerified
      };
    });
  }
  window.krQualityCatalog = scrub;
  window.krQualityRules = {roomCountFromTitle,titleMetro};
})();

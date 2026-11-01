// Rezsikövető – a panel betöltője. A valódi panel (rezsi-panel-fo.js) mindig a legfrissebb változatban töltődik be:
// a fájl módosítási ideje (Last-Modified) kerül az URL-be, így a böngésző/mobilalkalmazás gyorsítótára nem ad régit.
// Ez a kis fájl ritkán változik; a panel frissítés gombja új változatnál újratölti az oldalt.
const FO = new URL("./rezsi-panel-fo.js", import.meta.url).pathname;

async function verzio() {
  try {
    const v = await fetch(FO, { method: "HEAD", cache: "no-store" });
    return v.headers.get("last-modified") || v.headers.get("etag") || String(Date.now());
  } catch {
    return String(Date.now());
  }
}

window.huRezsiPanel = { fo: FO, verzio: await verzio(), ujVerzio: verzio };
await import(`${FO}?v=${encodeURIComponent(window.huRezsiPanel.verzio)}`);

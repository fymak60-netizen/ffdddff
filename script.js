/* ============================================================
   ليل طويل — script
   ============================================================ */

const SONGS = [
  { name: "ليلة هادية", artist: "مزاج · هدوء", len: "3:48", mood: 0,
    q: "lofi arabic night playlist هادئة" },
  { name: "دخان على السطح", artist: "مزاج · ليل", len: "4:12", mood: 0,
    q: "arabic chill oud night instrumental" },
  { name: "قهوة بعد منتصف الليل", artist: "مزاج · دافئ", len: "3:22", mood: 1,
    q: "arabic jazz cafe night playlist" },
  { name: "شارت ونجمة", artist: "مزاج · تركيز", len: "5:04", mood: 1,
    q: "deep focus arabic instrumental music" },
  { name: "نعناع بارد", artist: "مزاج · منعش", len: "3:36", mood: 1,
    q: "fresh chill house arabic remix" },
  { name: "على نار هادية", artist: "مزاج · حركة", len: "4:40", mood: 2,
    q: "arabic electronic night drive mix" },
  { name: "آخر نَفَس قبل الفجر", artist: "مزاج · سكون", len: "6:18", mood: 0,
    q: "ambient arabic dawn instrumental" },
  { name: "ليل طويل", artist: "مزاج · عنوان الليلة", len: "4:56", mood: 2,
    q: "ليل طويل اغنية عربية هادئة" },
];

const MOODS = ["هادي", "دافئ", "على نار"];

/* ---------- playlist ---------- */

const playlistEl = document.getElementById("playlist");
const pickResult = document.getElementById("pickResult");

function youtubeUrl(query) {
  return "https://www.youtube.com/results?search_query=" + encodeURIComponent(query);
}

function renderPlaylist(list) {
  playlistEl.innerHTML = "";
  list.forEach((song, i) => {
    const row = document.createElement("a");
    row.className = "track";
    row.href = youtubeUrl(song.q);
    row.target = "_blank";
    row.rel = "noopener noreferrer";
    row.innerHTML = `
      <span class="idx">${String(i + 1).padStart(2, "0")}</span>
      <span class="meta">
        <span class="name">${song.name}</span>
        <span class="artist">${song.artist} · ${MOODS[song.mood]}</span>
      </span>
      <span class="len">
        <span class="eq"><i></i><i></i><i></i></span>
        ${song.len}
      </span>
    `;
    playlistEl.appendChild(row);
  });
}

const moodRange = document.getElementById("moodRange");
const moodName = document.getElementById("moodName");

function currentMoodFilter() {
  return Number(moodRange.value);
}

function filteredSongs() {
  const m = currentMoodFilter();
  const subset = SONGS.filter((s) => s.mood === m);
  return subset.length ? subset : SONGS;
}

function updateMood() {
  const m = currentMoodFilter();
  moodName.textContent = MOODS[m];
  renderPlaylist(filteredSongs());
}

moodRange.addEventListener("input", updateMood);

function pickRandomSong() {
  const pool = filteredSongs();
  const song = pool[Math.floor(Math.random() * pool.length)];
  pickResult.innerHTML = `اخترنا لك: <b>${song.name}</b> — ${song.artist}`;
  // flash the matching row
  [...playlistEl.children].forEach((row) => {
    row.classList.remove("flash");
    if (row.querySelector(".name").textContent === song.name) {
      row.style.borderColor = "var(--accent)";
      row.style.background = "rgba(56,232,200,0.12)";
      setTimeout(() => {
        row.style.borderColor = "";
        row.style.background = "";
      }, 1800);
    }
  });
}

document.getElementById("pickSong").addEventListener("click", pickRandomSong);
document.getElementById("shuffleHero").addEventListener("click", () => {
  document.getElementById("music").scrollIntoView({ behavior: "smooth", block: "center" });
  setTimeout(pickRandomSong, 500);
});

/* ---------- hookah ---------- */

const device = document.getElementById("device");
const flavorName = document.getElementById("flavorName");
const puffCountEl = document.getElementById("puffCount");
const batteryBar = document.getElementById("batteryBar");
const smokeLayer = device.querySelector(".smoke");
const bodyEl = device.querySelector(".body");
const baseShadow = device.querySelector(".base-shadow");

let puffs = 0;
let battery = 100;
let currentColor = "#38e8c8";

function applyColor(color) {
  currentColor = color;
  document.documentElement.style.setProperty("--accent", color);
  bodyEl.style.boxShadow = `inset 0 1px 0 rgba(255,255,255,.15), 0 24px 60px -18px ${color}`;
  baseShadow.style.background = `radial-gradient(ellipse, ${color}, transparent 68%)`;
}

document.querySelectorAll(".flavor").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".flavor").forEach((b) => b.classList.remove("is-active"));
    btn.classList.add("is-active");
    flavorName.textContent = btn.dataset.name;
    applyColor(btn.dataset.color);
  });
});

function spawnSmoke() {
  const p = document.createElement("span");
  const dx = (Math.random() * 90 - 45).toFixed(0);
  p.style.setProperty("--dx", dx + "px");
  p.style.background = currentColor;
  p.style.animationDelay = Math.random() * 160 + "ms";
  smokeLayer.appendChild(p);
  setTimeout(() => p.remove(), 1200);
}

function puff() {
  if (battery <= 0) {
    pickResult.textContent = "البطارية فاضية… اشحنها وارجع. ☕";
    return;
  }
  puffs += 1;
  battery = Math.max(0, battery - 3);
  puffCountEl.textContent = puffs;
  batteryBar.style.width = battery + "%";
  if (battery < 25) batteryBar.style.opacity = "0.7";

  spawnSmoke();
  spawnSmoke();
  bodyEl.animate(
    [{ transform: "scale(1)" }, { transform: "scale(1.05, 0.98)" }, { transform: "scale(1)" }],
    { duration: 380, easing: "ease-out" }
  );
}

document.getElementById("puffBtn").addEventListener("click", puff);
device.addEventListener("click", puff);

/* ---------- calm mode ---------- */

const nightBtn = document.getElementById("nightMode");
const nightLabel = document.getElementById("nightModeLabel");

nightBtn.addEventListener("click", () => {
  const on = document.body.classList.toggle("calm");
  nightBtn.setAttribute("aria-pressed", String(on));
  nightLabel.textContent = on ? "رجّع الجو" : "ليل هادئ";
});

/* ---------- clock + night length ---------- */

const clockEl = document.getElementById("clock");
const nightLenEl = document.getElementById("nightLen");

function toArabicDigits(str) {
  return String(str).replace(/\d/g, (d) => "٠١٢٣٤٥٦٧٨٩"[d]);
}

function tickClock() {
  const now = new Date();
  const hh = String(now.getHours()).padStart(2, "0");
  const mm = String(now.getMinutes()).padStart(2, "0");
  clockEl.textContent = toArabicDigits(`${hh}:${mm}`);

  // الليل من ٢٠:٠٠ إلى ٠٥:٠٠ تقريبًا
  const hoursInto = (now.getHours() - 20 + 24) % 24;
  const total = 9;
  const left = Math.max(0, total - Math.min(hoursInto, total));
  nightLenEl.textContent =
    now.getHours() >= 5 && now.getHours() < 20
      ? "لسه بدري"
      : toArabicDigits(left) + " ساعات";
}

tickClock();
setInterval(tickClock, 15000);

/* ---------- reveal on scroll ---------- */

const revealTargets = document.querySelectorAll(
  ".section-head, .card, .track, .timeline li, .quote-band blockquote, .hookah-stage, .split-text, .playlist"
);
revealTargets.forEach((el) => el.classList.add("reveal"));

const io = new IntersectionObserver(
  (entries) => {
    entries.forEach((e) => {
      if (e.isIntersecting) {
        e.target.classList.add("in");
        io.unobserve(e.target);
      }
    });
  },
  { threshold: 0.12, rootMargin: "0px 0px -40px 0px" }
);

revealTargets.forEach((el) => io.observe(el));

/* ---------- init ---------- */

renderPlaylist(SONGS);
applyColor(currentColor);

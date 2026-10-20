const form = document.getElementById("form");
const input = document.getElementById("object");
const submit = document.getElementById("submit");
const statusEl = document.getElementById("status");
const exhibit = document.getElementById("exhibit");
const img = document.getElementById("image");
const developing = document.getElementById("developing");
const notes = document.getElementById("notes");
const promptEl = document.getElementById("image-prompt");

const FIELDS = ["artist_name", "artist_bio", "title", "year", "medium",
                "dimensions", "provenance", "credit_line", "extended_label"];

function setStatus(text, isError = false) {
  statusEl.textContent = text;
  statusEl.classList.toggle("error", isError);
}

async function postJSON(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  let data = {};
  try { data = await res.json(); } catch (_) { /* non-JSON error page */ }
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status}). Please try again.`);
  return data;
}

function showLabel(label) {
  // textContent (never innerHTML) so model output cannot inject markup.
  FIELDS.forEach((k) => { document.getElementById(k).textContent = label[k] || ""; });
  img.removeAttribute("src");
  img.alt = "";
  developing.hidden = false;
  developing.textContent = "The work is being installed…";
  notes.hidden = true;
  exhibit.hidden = false;
}

async function accession(objectText) {
  submit.disabled = true;
  setStatus("The curator is writing the wall label…");
  try {
    const { label } = await postJSON("/api/label", { object: objectText });
    showLabel(label);
    setStatus("Label approved. The installation crew is building the exhibition (this can take up to a minute)…");

    const { image, image_prompt } = await postJSON("/api/install", { label });
    img.src = image;
    img.alt = `Installation view of ${label.title} by ${label.artist_name}`;
    developing.hidden = true;
    promptEl.textContent = image_prompt;
    notes.hidden = false;
    setStatus(`Accessioned. Extended label: ${label.word_count} words.`);
  } catch (err) {
    developing.textContent = "Installation postponed.";
    setStatus(err.message, true);
  } finally {
    submit.disabled = false;
  }
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (text) accession(text);
});

document.querySelectorAll(".chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    input.value = chip.textContent;
    form.requestSubmit();
  });
});

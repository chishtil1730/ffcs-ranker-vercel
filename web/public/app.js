const fileInput = document.getElementById("fileInput");
const fileListEl = document.getElementById("fileList");
const submitBtn = document.getElementById("submitBtn");
const statusEl = document.getElementById("status");
const resultsEl = document.getElementById("results");
const dropzone = document.getElementById("dropzone");

let selectedFiles = [];

function renderFileList() {
  fileListEl.innerHTML = "";
  selectedFiles.forEach((file, i) => {
    const row = document.createElement("div");
    row.className = "file-item";
    row.innerHTML = `<span>${file.name}</span>`;
    const removeBtn = document.createElement("button");
    removeBtn.textContent = "✕";
    removeBtn.onclick = () => {
      selectedFiles.splice(i, 1);
      renderFileList();
    };
    row.appendChild(removeBtn);
    fileListEl.appendChild(row);
  });
  submitBtn.disabled = selectedFiles.length === 0;
}

fileInput.addEventListener("change", (e) => {
  selectedFiles = [...selectedFiles, ...Array.from(e.target.files)];
  renderFileList();
  fileInput.value = "";
});

["dragover", "dragleave", "drop"].forEach((evt) => {
  dropzone.addEventListener(evt, (e) => e.preventDefault());
});
dropzone.addEventListener("drop", (e) => {
  const dropped = Array.from(e.dataTransfer.files).filter((f) => f.type === "application/pdf");
  selectedFiles = [...selectedFiles, ...dropped];
  renderFileList();
});

function ratingColor(rating) {
  if (rating === null || rating === undefined) return "#999";
  const clamped = Math.max(0, Math.min(5, rating));
  const hue = (clamped / 5) * 120; // 0 = red, 120 = green
  return `hsl(${hue}, 70%, 42%)`;
}

function renderPdfBlock(pdfResult) {
  const card = document.createElement("div");
  card.className = "pdf-card";

  if (pdfResult.error) {
    card.innerHTML = `
      <div class="pdf-card-head">
        <div class="pdf-card-head-left">
          <h2>${pdfResult.filename}</h2>
          <span class="meta">Failed to process</span>
        </div>
      </div>
      <div class="error-msg">${pdfResult.error}</div>`;
    return card;
  }

  const { filename, results, stats } = pdfResult;

  const head = document.createElement("div");
  head.className = "pdf-card-head";
  head.innerHTML = `
    <div class="pdf-card-head-left">
      <h2>${filename}</h2>
      <span class="meta">${stats.total_slots} slots · ${stats.unique_faculty} faculty · ${stats.not_found} not found</span>
    </div>
    <svg class="chevron" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"></polyline></svg>`;
  card.appendChild(head);

  const preview = document.createElement("div");
  preview.className = "preview";
  results.slice(0, 3).forEach((r) => {
    const pill = document.createElement("span");
    pill.className = "preview-pill";
    const dotColor = r.found ? ratingColor(r.rating) : "#f87171";
    const name = r.found ? (r.matched_faculty || r.faculty_pdf) : r.faculty_pdf;
    pill.innerHTML = `<span class="preview-dot" style="background:${dotColor}"></span>${name}`;
    preview.appendChild(pill);
  });
  if (results.length > 3) {
    const more = document.createElement("span");
    more.className = "preview-pill";
    more.textContent = `+${results.length - 3} more`;
    preview.appendChild(more);
  }
  card.appendChild(preview);

  const body = document.createElement("div");
  body.className = "pdf-card-body";
  const table = document.createElement("table");
  table.innerHTML = `
    <thead>
      <tr>
        <th>Faculty</th>
        <th>Slot</th>
        <th>Venue</th>
        <th>Rating</th>
        <th>Difficulty</th>
        <th>Reviews</th>
      </tr>
    </thead>
    <tbody></tbody>`;
  const tbody = table.querySelector("tbody");

  results.forEach((r) => {
    const tr = document.createElement("tr");
    const nameCell = r.found && r.matched_faculty !== r.faculty_pdf
      ? `<span class="faculty-name">${r.matched_faculty}</span><span class="faculty-sub">as "${r.faculty_pdf}"</span>`
      : `<span class="faculty-name">${r.faculty_pdf}</span>`;

    const ratingCell = r.found
      ? `<span class="rating-pill" style="background:${ratingColor(r.rating)}">${r.rating ?? "–"}</span>`
      : `<span class="not-found">Not found</span>`;

    tr.innerHTML = `
      <td>${nameCell}</td>
      <td>${r.slot}</td>
      <td>${r.venue}</td>
      <td>${ratingCell}</td>
      <td>${r.difficulty ?? '<span class="dash">–</span>'}</td>
      <td>${r.review_count ?? '<span class="dash">–</span>'}</td>`;
    tbody.appendChild(tr);
  });

  body.appendChild(table);
  card.appendChild(body);

  head.addEventListener("click", () => {
    card.classList.toggle("open");
  });

  return card;
}

submitBtn.addEventListener("click", async () => {
  if (selectedFiles.length === 0) return;
  submitBtn.disabled = true;
  statusEl.textContent = "Processing PDFs…";
  resultsEl.innerHTML = "";

  const formData = new FormData();
  selectedFiles.forEach((f) => formData.append("pdfs", f));

  try {
    const res = await fetch("/api/parse", { method: "POST", body: formData });
    const data = await res.json();

    if (!res.ok) {
      statusEl.textContent = data.error || "Something went wrong.";
      submitBtn.disabled = false;
      return;
    }

    statusEl.textContent = "";
    data.files.forEach((pdfResult) => {
      resultsEl.appendChild(renderPdfBlock(pdfResult));
    });
  } catch (err) {
    statusEl.textContent = "Network error: " + err.message;
  } finally {
    submitBtn.disabled = false;
  }
});

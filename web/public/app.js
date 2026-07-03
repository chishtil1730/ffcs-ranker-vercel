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
  const block = document.createElement("div");
  block.className = "pdf-block";

  if (pdfResult.error) {
    block.innerHTML = `
      <div class="pdf-header">
        <h2>${pdfResult.filename}</h2>
        <span class="meta">Failed to process</span>
      </div>
      <div style="padding:16px 20px;color:#b91c1c;">${pdfResult.error}</div>`;
    return block;
  }

  const { filename, results, stats } = pdfResult;

  const header = document.createElement("div");
  header.className = "pdf-header";
  header.innerHTML = `
    <h2>${filename}</h2>
    <span class="meta">${stats.total_slots} slots · ${stats.unique_faculty} faculty · ${stats.not_found} not found</span>`;
  block.appendChild(header);

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

  block.appendChild(table);
  return block;
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

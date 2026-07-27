let parsedUnits = null;

const fileInput = document.getElementById("file-input");
const uploadBox = document.getElementById("upload-box");
const uploadLabel = document.getElementById("upload-label");
const uploadStatus = document.getElementById("upload-status");
const optionsCard = document.getElementById("options-card");
const unitSelect = document.getElementById("unit-select");
const bookTitleInput = document.getElementById("book-title");
const generateBtn = document.getElementById("generate-btn");

fileInput.addEventListener("change", async () => {
  const file = fileInput.files[0];
  if (!file) return;

  uploadLabel.textContent = `⏳ ${file.name} 분석 중...`;
  uploadStatus.textContent = "PDF에서 단어를 추출하고 있어요. 잠시만 기다려주세요 (수 초~수십 초 소요)";

  const formData = new FormData();
  formData.append("file", file);

  try {
    const res = await fetch("/api/parse", { method: "POST", body: formData });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "분석 실패");
    }
    const data = await res.json();
    parsedUnits = data.units;

    unitSelect.innerHTML = "";
    parsedUnits.forEach((u, i) => {
      const opt = document.createElement("option");
      opt.value = i;
      opt.textContent = `${u.unit_title} (${u.words.length}단어)`;
      unitSelect.appendChild(opt);
    });

    uploadLabel.textContent = `✅ ${file.name}`;
    uploadStatus.textContent = `${parsedUnits.length}개 유닛을 찾았어요.`;
    optionsCard.style.display = "block";
  } catch (e) {
    uploadLabel.textContent = "📄 단어책 PDF 업로드";
    uploadStatus.textContent = `❌ 오류: ${e.message}`;
  }
});

generateBtn.addEventListener("click", async () => {
  if (!parsedUnits) return;
  const idx = parseInt(unitSelect.value, 10);
  const unit = parsedUnits[idx];

  const payload = {
    academy_name: document.getElementById("academy-name").value || "학원명",
    book_title: bookTitleInput.value || "",
    unit_title: unit.unit_title,
    words: unit.words,
    shuffle: document.getElementById("shuffle-check").checked,
    direction: document.getElementById("direction-select").value,
  };

  generateBtn.disabled = true;
  generateBtn.textContent = "생성 중...";

  try {
    const res = await fetch("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error("PDF 생성 실패");
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${unit.unit_title.replace(/\s+/g, "_")}_시험지.pdf`;
    document.body.appendChild(a);
    a.click();
    a.remove();
  } catch (e) {
    alert("오류: " + e.message);
  } finally {
    generateBtn.disabled = false;
    generateBtn.textContent = "📥 시험지 PDF 만들기";
  }
});

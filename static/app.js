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
    if (parsedUnits.length > 1) {
      const totalWords = parsedUnits.reduce((s, u) => s + u.words.length, 0);
      const allOpt = document.createElement("option");
      allOpt.value = "all";
      allOpt.textContent = `📚 책 전체 (${parsedUnits.length}개 유닛 · ${totalWords}단어)`;
      unitSelect.appendChild(allOpt);
    }
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
    uploadLabel.textContent = "📄 단어책 PDF / 엑셀 업로드";
    uploadStatus.textContent = `❌ 오류: ${e.message}`;
  }
});

generateBtn.addEventListener("click", async () => {
  if (!parsedUnits) return;

  const academyName = document.getElementById("academy-name").value || "학원명";
  const bookTitle = bookTitleInput.value || "";
  const shuffle = document.getElementById("shuffle-check").checked;
  const direction = document.getElementById("direction-select").value;
  const isAll = unitSelect.value === "all";

  let endpoint, payload, filename;
  if (isAll) {
    endpoint = "/api/generate-all";
    payload = { academy_name: academyName, book_title: bookTitle, units: parsedUnits, shuffle, direction };
    filename = `${(bookTitle || "책전체").replace(/\s+/g, "_")}_전체_시험지.pdf`;
  } else {
    const unit = parsedUnits[parseInt(unitSelect.value, 10)];
    endpoint = "/api/generate";
    payload = { academy_name: academyName, book_title: bookTitle, unit_title: unit.unit_title, words: unit.words, shuffle, direction };
    filename = `${unit.unit_title.replace(/\s+/g, "_")}_시험지.pdf`;
  }

  generateBtn.disabled = true;
  generateBtn.textContent = isAll ? "책 전체 생성 중... (조금 걸려요)" : "생성 중...";

  try {
    const res = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      let detail = "PDF 생성 실패";
      try {
        const err = await res.json();
        detail = err.detail || detail;
      } catch (_) {}
      throw new Error(detail);
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
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

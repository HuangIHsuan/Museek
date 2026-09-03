const pptxgen = require('pptxgenjs');

const pptx = new pptxgen();
pptx.layout = 'LAYOUT_WIDE';
pptx.author = 'Claude';
pptx.company = 'Museek';
pptx.subject = 'Museek pitch deck';
pptx.title = 'Museek 音樂探索 Agent';
pptx.lang = 'zh-TW';
pptx.theme = {
  headFontFace: 'Microsoft JhengHei',
  bodyFontFace: 'Microsoft JhengHei',
  lang: 'zh-TW'
};

const COLORS = {
  navy: '16324F',
  blue: '2E5B88',
  lightBlue: 'EAF2FB',
  teal: '3AAFA9',
  gold: 'F4B942',
  red: 'D95D39',
  text: '1F2937',
  muted: '6B7280',
  line: 'D9E2EC',
  white: 'FFFFFF',
  soft: 'F8FAFC',
  green: '2F855A'
};

function addTopBar(slide) {
  slide.addShape(pptx.ShapeType.rect, {
    x: 0,
    y: 0,
    w: 13.333,
    h: 0.28,
    line: { color: COLORS.navy, transparency: 100 },
    fill: { color: COLORS.navy }
  });
}

function addHeader(slide, title, subtitle) {
  addTopBar(slide);
  slide.addText(title, {
    x: 0.65,
    y: 0.62,
    w: 10.8,
    h: 0.4,
    fontFace: 'Microsoft JhengHei',
    fontSize: 20,
    bold: true,
    color: COLORS.navy,
    fit: 'shrink',
    margin: 0
  });
  if (subtitle) {
    slide.addText(subtitle, {
      x: 0.65,
      y: 1.05,
      w: 11.2,
      h: 0.34,
      fontFace: 'Microsoft JhengHei',
      fontSize: 9,
      color: COLORS.muted,
      fit: 'shrink',
      margin: 0
    });
  }
}

function addFooter(slide, page) {
  slide.addText(`Museek | ${page}`, {
    x: 11.45,
    y: 7.02,
    w: 1.35,
    h: 0.18,
    align: 'right',
    fontFace: 'Microsoft JhengHei',
    fontSize: 8,
    color: COLORS.muted,
    margin: 0
  });
}

function addSectionTag(slide, label) {
  slide.addShape(pptx.ShapeType.roundRect, {
    x: 0.66,
    y: 0.38,
    w: 1.18,
    h: 0.22,
    rectRadius: 0.04,
    line: { color: COLORS.teal, transparency: 100 },
    fill: { color: 'DFF6F5' }
  });
  slide.addText(label, {
    x: 0.76,
    y: 0.43,
    w: 0.98,
    h: 0.1,
    fontFace: 'Microsoft JhengHei',
    fontSize: 8,
    bold: true,
    color: COLORS.teal,
    align: 'center',
    margin: 0
  });
}

function addBullets(slide, items, opts = {}) {
  const x = opts.x ?? 0.9;
  const y = opts.y ?? 1.6;
  const w = opts.w ?? 5.1;
  const h = opts.h ?? 4.2;
  const fontSize = opts.fontSize ?? 15;
  const color = opts.color ?? COLORS.text;
  const bulletIndent = opts.bulletIndent ?? 14;
  const hanging = opts.hanging ?? 3;

  const runs = [];
  items.forEach((item, idx) => {
    if (idx > 0) runs.push({ text: '\n' });
    runs.push({
      text: item,
      options: {
        bullet: { indent: bulletIndent },
        hanging,
        breakLine: false
      }
    });
  });

  slide.addText(runs, {
    x,
    y,
    w,
    h,
    fontFace: 'Microsoft JhengHei',
    fontSize,
    color,
    valign: 'top',
    paraSpaceAfterPt: 8,
    fit: 'shrink',
    margin: 0.03
  });
}

function addQuote(slide, text, opts = {}) {
  const x = opts.x ?? 0.95;
  const y = opts.y ?? 5.8;
  const w = opts.w ?? 5.6;
  const h = opts.h ?? 0.7;
  slide.addShape(pptx.ShapeType.roundRect, {
    x,
    y,
    w,
    h,
    rectRadius: 0.04,
    line: { color: COLORS.lightBlue, transparency: 100 },
    fill: { color: COLORS.lightBlue }
  });
  slide.addText(text, {
    x: x + 0.16,
    y: y + 0.12,
    w: w - 0.32,
    h: h - 0.18,
    fontFace: 'Microsoft JhengHei',
    fontSize: 11,
    italic: true,
    color: COLORS.blue,
    align: 'center',
    valign: 'mid',
    fit: 'shrink',
    margin: 0
  });
}

function addCard(slide, cfg) {
  slide.addShape(pptx.ShapeType.roundRect, {
    x: cfg.x,
    y: cfg.y,
    w: cfg.w,
    h: cfg.h,
    rectRadius: 0.05,
    line: { color: cfg.line || COLORS.line, pt: 1 },
    fill: { color: cfg.fill || COLORS.white }
  });
}

function addFlowArrow(slide, x, y, w, h) {
  slide.addShape(pptx.ShapeType.line, {
    x,
    y,
    w,
    h,
    line: { color: COLORS.blue, pt: 1.1, endArrowType: 'triangle' }
  });
}

// Slide 1
{
  const slide = pptx.addSlide();
  addTopBar(slide);
  slide.addShape(pptx.ShapeType.rect, {
    x: 0.85,
    y: 1.2,
    w: 0.14,
    h: 4.6,
    line: { color: COLORS.teal, transparency: 100 },
    fill: { color: COLORS.teal }
  });
  slide.addText('Museek', {
    x: 1.25,
    y: 1.45,
    w: 4.7,
    h: 0.55,
    fontFace: 'Microsoft JhengHei',
    fontSize: 24,
    bold: true,
    color: COLORS.navy,
    margin: 0
  });
  slide.addText('你的音樂探索夥伴，而不只是推薦引擎', {
    x: 1.25,
    y: 2.1,
    w: 5.5,
    h: 0.45,
    fontFace: 'Microsoft JhengHei',
    fontSize: 16,
    color: COLORS.text,
    fit: 'shrink',
    margin: 0
  });
  slide.addText('用一句話描述心情，Agent 主動探索、分析，並解釋「為什麼你會喜歡」。', {
    x: 1.25,
    y: 2.8,
    w: 5.6,
    h: 0.7,
    fontFace: 'Microsoft JhengHei',
    fontSize: 12,
    color: COLORS.muted,
    fit: 'shrink',
    margin: 0
  });

  addCard(slide, { x: 7.2, y: 1.3, w: 5.0, h: 4.6, fill: COLORS.soft });
  slide.addText('核心關鍵詞', {
    x: 7.6,
    y: 1.7,
    w: 2,
    h: 0.2,
    fontSize: 11,
    bold: true,
    color: COLORS.navy,
    margin: 0
  });
  const tags = [
    ['AI Agent', COLORS.blue, 'EAF2FB'],
    ['Discovery', COLORS.teal, 'DFF6F5'],
    ['Music API', '8A5A00', 'FFF4D6'],
    ['Reasoning', COLORS.red, 'FDE9E2'],
    ['Feedback Loop', COLORS.green, 'E6F4EA']
  ];
  tags.forEach(([label, color, fill], idx) => {
    const row = Math.floor(idx / 2);
    const col = idx % 2;
    slide.addShape(pptx.ShapeType.roundRect, {
      x: 7.6 + col * 2.05,
      y: 2.2 + row * 0.82,
      w: 1.72,
      h: 0.38,
      rectRadius: 0.04,
      line: { color, transparency: 100 },
      fill: { color: fill }
    });
    slide.addText(label, {
      x: 7.72 + col * 2.05,
      y: 2.31 + row * 0.82,
      w: 1.46,
      h: 0.12,
      fontSize: 9,
      bold: true,
      color,
      align: 'center',
      fit: 'shrink',
      margin: 0
    });
  });
  slide.addText('從「被動接受推薦」\n走向「主動探索音樂」', {
    x: 7.75,
    y: 4.2,
    w: 3.8,
    h: 1.0,
    fontSize: 17,
    bold: true,
    color: COLORS.navy,
    align: 'center',
    valign: 'mid',
    fit: 'shrink',
    margin: 0
  });
  addFooter(slide, 1);
}

// Slide 2
{
  const slide = pptx.addSlide();
  addSectionTag(slide, 'Problem');
  addHeader(slide, '問題動機', '現有推薦系統擅長相似推薦，但不擅長主動探索');
  addBullets(slide, [
    '推薦系統擅長「更多相似的歌」，但難以幫使用者跳出舒適圈',
    '當使用者想探索新音樂時，仍要自己搜尋、篩選、比對',
    '自然語言需求很真實，但傳統搜尋無法完整承接'
  ], { x: 0.95, y: 1.75, w: 5.5, h: 2.6, fontSize: 15 });
  addQuote(slide, '「我最近很喜歡某個歌手，想找沒聽過、比較冷門、但氛圍相近的音樂。」', {
    x: 0.95,
    y: 5.35,
    w: 5.7,
    h: 0.85
  });

  addCard(slide, { x: 7.15, y: 1.8, w: 4.9, h: 4.4, fill: 'FCFCFD' });
  slide.addText('傳統流程', {
    x: 7.55,
    y: 2.1,
    w: 1.5,
    h: 0.18,
    fontSize: 11,
    bold: true,
    color: COLORS.navy,
    margin: 0
  });
  const steps = ['自己描述需求', '自己搜尋歌手 / 歌單', '自己過濾熱門歌', '自己驗證是否真的喜歡'];
  steps.forEach((step, i) => {
    slide.addShape(pptx.ShapeType.ellipse, {
      x: 7.55,
      y: 2.55 + i * 0.75,
      w: 0.3,
      h: 0.3,
      line: { color: COLORS.blue, transparency: 100 },
      fill: { color: COLORS.blue }
    });
    slide.addText(String(i + 1), {
      x: 7.645,
      y: 2.64 + i * 0.75,
      w: 0.11,
      h: 0.07,
      fontSize: 8,
      bold: true,
      color: COLORS.white,
      align: 'center',
      margin: 0
    });
    slide.addText(step, {
      x: 8.02,
      y: 2.58 + i * 0.75,
      w: 3.35,
      h: 0.18,
      fontSize: 12,
      color: COLORS.text,
      fit: 'shrink',
      margin: 0
    });
  });
  slide.addText('痛點：探索成本高、結果不穩定', {
    x: 7.55,
    y: 5.72,
    w: 3.9,
    h: 0.18,
    fontSize: 12,
    bold: true,
    color: COLORS.red,
    margin: 0
  });
  addFooter(slide, 2);
}

// Slide 3
{
  const slide = pptx.addSlide();
  addSectionTag(slide, 'Solution');
  addHeader(slide, '我們的主張', '讓 AI 從推薦工具進化為音樂探索夥伴');
  slide.addShape(pptx.ShapeType.roundRect, {
    x: 0.95,
    y: 1.65,
    w: 11.35,
    h: 0.82,
    rectRadius: 0.05,
    line: { color: COLORS.lightBlue, transparency: 100 },
    fill: { color: COLORS.lightBlue }
  });
  slide.addText('理解需求 → 主動探索 → 客觀分析 → 解釋理由', {
    x: 1.2,
    y: 1.94,
    w: 10.8,
    h: 0.18,
    fontSize: 18,
    bold: true,
    color: COLORS.navy,
    align: 'center',
    fit: 'shrink',
    margin: 0
  });
  const blocks = [
    ['LLM', '理解自然語言需求'],
    ['AI Agent', '規劃流程與工具調用'],
    ['Music API', '取得歌曲與音訊特徵'],
    ['Web Search', '補充樂評與風格脈絡'],
    ['Reasoning', '生成有依據的推薦說明'],
    ['Personalization', '從回饋持續調整偏好']
  ];
  blocks.forEach(([title, desc], i) => {
    const col = i % 3;
    const row = Math.floor(i / 3);
    const x = 1.0 + col * 3.9;
    const y = 2.9 + row * 1.45;
    addCard(slide, { x, y, w: 3.2, h: 0.98, fill: COLORS.white });
    slide.addText(title, {
      x: x + 0.18,
      y: y + 0.23,
      w: 2.8,
      h: 0.16,
      fontSize: 12,
      bold: true,
      color: COLORS.blue,
      align: 'center',
      margin: 0
    });
    slide.addText(desc, {
      x: x + 0.18,
      y: y + 0.52,
      w: 2.8,
      h: 0.18,
      fontSize: 10,
      color: COLORS.text,
      align: 'center',
      fit: 'shrink',
      margin: 0
    });
  });
  addFooter(slide, 3);
}

// Slide 4
{
  const slide = pptx.addSlide();
  addSectionTag(slide, 'Core Idea');
  addHeader(slide, '核心差異化：Discovery Distance', '不是找最像的歌，而是找「夠像、但有新鮮感」的歌');
  slide.addText('Discovery Score = Similarity × Familiarity Distance × Popularity Factor', {
    x: 0.95,
    y: 1.7,
    w: 10.6,
    h: 0.2,
    fontSize: 15,
    bold: true,
    color: COLORS.navy,
    fit: 'shrink',
    margin: 0
  });
  slide.addText('理想候選應該與使用者品味有關聯，但不能近到只是換一首相似歌。', {
    x: 0.95,
    y: 2.0,
    w: 10.6,
    h: 0.18,
    fontSize: 10,
    color: COLORS.muted,
    fit: 'shrink',
    margin: 0
  });

  slide.addTable([
    [
      { text: 'Song', options: { bold: true, color: COLORS.white, align: 'center' } },
      { text: '相似度', options: { bold: true, color: COLORS.white, align: 'center' } },
      { text: '熟悉度距離', options: { bold: true, color: COLORS.white, align: 'center' } },
      { text: '熱門度', options: { bold: true, color: COLORS.white, align: 'center' } },
      { text: 'Discovery', options: { bold: true, color: COLORS.white, align: 'center' } }
    ],
    ['A', '0.95', '近', '高', '低'],
    ['B', '0.82', '中', '中', '高'],
    ['C', '0.65', '遠', '低', '中'],
    ['D', '0.30', '極遠', '低', '低']
  ], {
    x: 1.0,
    y: 2.45,
    w: 5.95,
    h: 2.2,
    border: { type: 'solid', color: COLORS.line, pt: 1 },
    fill: 'FFFFFF',
    color: COLORS.text,
    fontFace: 'Microsoft JhengHei',
    fontSize: 10,
    rowH: 0.42,
    colW: [0.8, 1.0, 1.35, 0.95, 1.15],
    autoFit: false,
    align: 'center',
    valign: 'mid',
    margin: 0.03,
    fillHeader: COLORS.navy
  });
  slide.addText('★ B 是最值得探索的平衡點', {
    x: 1.1,
    y: 4.85,
    w: 3.3,
    h: 0.16,
    fontSize: 11,
    bold: true,
    color: COLORS.green,
    margin: 0
  });

  addCard(slide, { x: 7.45, y: 2.35, w: 4.5, h: 2.95, fill: COLORS.soft });
  slide.addText('用一句話解釋', {
    x: 7.8,
    y: 2.68,
    w: 1.8,
    h: 0.16,
    fontSize: 11,
    bold: true,
    color: COLORS.navy,
    margin: 0
  });
  slide.addText('Museek 推薦的是：\n\n「你有機會喜歡，\n但平常不會自己找到的音樂」', {
    x: 7.9,
    y: 3.15,
    w: 3.6,
    h: 1.45,
    fontSize: 16,
    bold: true,
    color: COLORS.text,
    align: 'center',
    valign: 'mid',
    fit: 'shrink',
    margin: 0
  });
  addFooter(slide, 4);
}

// Slide 5
{
  const slide = pptx.addSlide();
  addSectionTag(slide, 'Architecture');
  addHeader(slide, '系統架構', '以 Agent 協調器串接搜尋、研究、推理與驗證');

  const leftX = 0.95;
  const rightX = 7.1;
  const boxW = 5.1;
  const boxH = 0.72;
  const gap = 0.35;
  const leftItems = [
    ['使用者自然語言需求', COLORS.soft, COLORS.text],
    ['Museek Agent 協調器', 'EAF2FB', COLORS.navy],
    ['Music Search Tool\nYouTube + ReccoBeats', COLORS.white, COLORS.text],
    ['Discovery Ranking', 'DFF6F5', COLORS.teal]
  ];
  const rightItems = [
    ['Web Research Tool\n風格 / 樂評 / 社群', COLORS.white, COLORS.text],
    ['Recommendation Reasoning Agent', COLORS.white, COLORS.text],
    ['驗證 videoId', 'FFF4D6', '8A5A00'],
    ['前端播放器 + 使用者回饋', 'FDE9E2', COLORS.red]
  ];

  leftItems.forEach(([label, fill, color], i) => {
    const y = 1.8 + i * (boxH + gap);
    addCard(slide, { x: leftX, y, w: boxW, h: boxH, fill });
    slide.addText(label, {
      x: leftX + 0.18,
      y: y + 0.2,
      w: boxW - 0.36,
      h: boxH - 0.18,
      fontSize: 12,
      bold: true,
      color,
      align: 'center',
      valign: 'mid',
      fit: 'shrink',
      margin: 0
    });
    if (i < leftItems.length - 1) addFlowArrow(slide, leftX + boxW / 2, y + boxH, 0, gap);
  });

  rightItems.forEach(([label, fill, color], i) => {
    const y = 1.8 + i * (boxH + gap);
    addCard(slide, { x: rightX, y, w: boxW, h: boxH, fill });
    slide.addText(label, {
      x: rightX + 0.18,
      y: y + 0.2,
      w: boxW - 0.36,
      h: boxH - 0.18,
      fontSize: 12,
      bold: true,
      color,
      align: 'center',
      valign: 'mid',
      fit: 'shrink',
      margin: 0
    });
    if (i < rightItems.length - 1) addFlowArrow(slide, rightX + boxW / 2, y + boxH, 0, gap);
  });

  slide.addShape(pptx.ShapeType.line, {
    x: 6.05,
    y: 2.55,
    w: 1.05,
    h: 0,
    line: { color: COLORS.blue, pt: 1.1, endArrowType: 'triangle' }
  });
  slide.addShape(pptx.ShapeType.line, {
    x: 6.05,
    y: 4.67,
    w: 1.05,
    h: -1.42,
    line: { color: COLORS.blue, pt: 1.1, endArrowType: 'triangle' }
  });
  slide.addShape(pptx.ShapeType.line, {
    x: 6.05,
    y: 4.67,
    w: 1.05,
    h: 0,
    line: { color: COLORS.blue, pt: 1.1, endArrowType: 'triangle' }
  });
  addFooter(slide, 5);
}

// Slide 6
{
  const slide = pptx.addSlide();
  addSectionTag(slide, 'Components');
  addHeader(slide, '三個核心元件', '不是 Search A vs Search B，而是 Retrieval / Research / Reasoning 的分工');
  const cards = [
    {
      title: 'Music Search Tool',
      subtitle: 'Music Retrieval',
      body: ['找 track / artist / album', '取得 playlist 與音訊特徵', '驗證 YouTube video'],
      x: 0.9,
      fill: 'EAF2FB',
      accent: COLORS.blue
    },
    {
      title: 'Web Research Tool',
      subtitle: 'Music Research',
      body: ['查藝人風格與訪談', '補充樂評與社群討論', '提供音樂脈絡資訊'],
      x: 4.45,
      fill: 'DFF6F5',
      accent: COLORS.teal
    },
    {
      title: 'Recommendation Reasoning Agent',
      subtitle: 'Explain Why',
      body: ['依 audio features 推導理由', '連結使用者偏好與候選歌', '輸出可解釋推薦說明'],
      x: 8.0,
      fill: 'FFF4D6',
      accent: '8A5A00'
    }
  ];
  cards.forEach((card) => {
    addCard(slide, { x: card.x, y: 1.95, w: 3.2, h: 3.45, fill: card.fill });
    slide.addText(card.title, {
      x: card.x + 0.16,
      y: 2.25,
      w: 2.88,
      h: 0.3,
      fontSize: 13,
      bold: true,
      color: card.accent,
      align: 'center',
      fit: 'shrink',
      margin: 0
    });
    slide.addText(card.subtitle, {
      x: card.x + 0.2,
      y: 2.62,
      w: 2.8,
      h: 0.14,
      fontSize: 9,
      bold: true,
      color: COLORS.muted,
      align: 'center',
      margin: 0
    });
    addBullets(slide, card.body, {
      x: card.x + 0.2,
      y: 3.0,
      w: 2.72,
      h: 1.8,
      fontSize: 11,
      bulletIndent: 11,
      hanging: 3
    });
  });
  addQuote(slide, '關鍵不是做更多搜尋，而是把「找資料、補脈絡、解釋原因」拆成不同能力。', {
    x: 1.2,
    y: 5.95,
    w: 10.9,
    h: 0.62
  });
  addFooter(slide, 6);
}

// Slide 7
{
  const slide = pptx.addSlide();
  addSectionTag(slide, 'Pipeline');
  addHeader(slide, '資料流 Pipeline', '以客觀音訊特徵建立 taste profile，再逐步收斂到可播放結果');
  const flow = [
    '使用者 Playlist',
    '取得 items + Cache',
    '建立 User Taste Profile',
    'ReccoBeats 找候選 30 首',
    'Discovery Ranking',
    'Top 8',
    'YouTube 驗證',
    'Top 5 有效 videoId'
  ];
  flow.forEach((label, i) => {
    const x = 0.72 + i * 1.54;
    addCard(slide, { x, y: 2.45, w: 1.26, h: 0.9, fill: i % 2 === 0 ? COLORS.white : COLORS.soft });
    slide.addText(label, {
      x: x + 0.07,
      y: 2.73,
      w: 1.12,
      h: 0.28,
      fontSize: 9,
      bold: i === 4 || i === 7,
      color: i === 4 ? COLORS.teal : COLORS.text,
      align: 'center',
      valign: 'mid',
      fit: 'shrink',
      margin: 0
    });
    if (i < flow.length - 1) addFlowArrow(slide, x + 1.26, 2.9, 0.28, 0);
  });

  addCard(slide, { x: 1.1, y: 4.3, w: 11.0, h: 1.4, fill: COLORS.lightBlue, line: COLORS.lightBlue });
  slide.addText('Audio Features 來源：ReccoBeats（免費、免 API Key）', {
    x: 1.4,
    y: 4.65,
    w: 4.7,
    h: 0.16,
    fontSize: 11,
    bold: true,
    color: COLORS.navy,
    margin: 0
  });
  slide.addText('tempo · energy · danceability · valence · acousticness · instrumentalness · liveness · loudness · speechiness', {
    x: 1.4,
    y: 5.0,
    w: 10.2,
    h: 0.16,
    fontSize: 10,
    color: COLORS.text,
    align: 'center',
    fit: 'shrink',
    margin: 0
  });
  slide.addText('不讓 LLM 猜 BPM，一切基於客觀數據。', {
    x: 3.8,
    y: 5.3,
    w: 4.6,
    h: 0.14,
    fontSize: 10,
    italic: true,
    color: COLORS.blue,
    align: 'center',
    margin: 0
  });
  addFooter(slide, 7);
}

// Slide 8
{
  const slide = pptx.addSlide();
  addSectionTag(slide, 'Reasoning');
  addHeader(slide, 'Reasoning Agent 如何「不亂掰」', 'LLM 的角色是詮釋數據，不是憑空猜測歌曲特徵');
  addCard(slide, { x: 0.95, y: 1.9, w: 5.2, h: 3.1, fill: 'FCFCFD' });
  slide.addText('輸入：客觀資料', {
    x: 1.22,
    y: 2.18,
    w: 1.8,
    h: 0.16,
    fontSize: 11,
    bold: true,
    color: COLORS.navy,
    margin: 0
  });
  slide.addText('{\n  user_profile: { avg_energy: 0.42, avg_valence: 0.51,\n                  favorite_genres: ["R&B", "Neo Soul"] },\n  candidate:    { energy: 0.45, valence: 0.55,\n                  acousticness: 0.72, tempo: 82 }\n}', {
    x: 1.22,
    y: 2.56,
    w: 4.55,
    h: 1.9,
    fontFace: 'Consolas',
    fontSize: 9,
    color: COLORS.text,
    fit: 'shrink',
    margin: 0.03
  });
  addFlowArrow(slide, 6.25, 3.35, 0.7, 0);
  addCard(slide, { x: 7.15, y: 1.9, w: 5.0, h: 3.1, fill: COLORS.soft });
  slide.addText('輸出：有根據的解釋', {
    x: 7.48,
    y: 2.18,
    w: 2.1,
    h: 0.16,
    fontSize: 11,
    bold: true,
    color: COLORS.navy,
    margin: 0
  });
  slide.addText('「這首歌的 Energy、Valence 與你偏好接近，但 Acousticness 更高，符合你想探索更溫暖、自然音色的需求。」', {
    x: 7.48,
    y: 2.7,
    w: 4.25,
    h: 1.35,
    fontSize: 14,
    color: COLORS.text,
    fit: 'shrink',
    valign: 'mid',
    margin: 0
  });
  addQuote(slide, '重點：LLM 只負責把客觀特徵轉成自然語言，不負責捏造事實。', {
    x: 1.4,
    y: 5.65,
    w: 10.4,
    h: 0.68
  });
  addFooter(slide, 8);
}

// Slide 9
{
  const slide = pptx.addSlide();
  addSectionTag(slide, 'Safety');
  addHeader(slide, '安全設計：AI 輸出 → 確定性驗證', '不靠 prompt 限制，靠程式驗證擋住幻覺與假連結');
  const flow = [
    'LLM 只輸出\ntitle + artist',
    'Backend\n實際搜尋',
    'YouTube API\n查詢 videoId',
    '驗證通過才\n進推薦清單',
    '前端播放器\n只吃有效 videoId'
  ];
  flow.forEach((label, i) => {
    const x = 0.8 + i * 2.45;
    const fill = i === 0 ? 'EAF2FB' : i === 3 ? 'DFF6F5' : i === 4 ? 'FFF4D6' : COLORS.white;
    const color = i === 0 ? COLORS.navy : i === 3 ? COLORS.teal : i === 4 ? '8A5A00' : COLORS.text;
    addCard(slide, { x, y: 2.55, w: 1.9, h: 0.98, fill });
    slide.addText(label, {
      x: x + 0.12,
      y: 2.86,
      w: 1.66,
      h: 0.3,
      fontSize: 10,
      bold: true,
      color,
      align: 'center',
      valign: 'mid',
      fit: 'shrink',
      margin: 0
    });
    if (i < flow.length - 1) addFlowArrow(slide, x + 1.9, 3.04, 0.55, 0);
  });
  slide.addShape(pptx.ShapeType.roundRect, {
    x: 1.65,
    y: 4.55,
    w: 10.05,
    h: 0.88,
    rectRadius: 0.05,
    line: { color: COLORS.red, pt: 1 },
    fill: { color: 'FFF6F4' }
  });
  slide.addText('絕不讓 LLM 直接生成 URL；查不到 videoId 的歌曲會被自動丟棄。', {
    x: 1.95,
    y: 4.85,
    w: 9.45,
    h: 0.18,
    fontSize: 13,
    bold: true,
    color: COLORS.red,
    align: 'center',
    fit: 'shrink',
    margin: 0
  });
  addFooter(slide, 9);
}

// Slide 10
{
  const slide = pptx.addSlide();
  addSectionTag(slide, 'Learning');
  addHeader(slide, '回饋學習迴圈', '評分不是裝飾，而是直接影響下一輪推薦結果');
  slide.addText('Museek 推薦 5 首', {
    x: 1.0,
    y: 2.0,
    w: 1.75,
    h: 0.18,
    fontSize: 15,
    bold: true,
    color: COLORS.navy,
    margin: 0
  });
  slide.addText('👍 Song A   👎 Song B   👍 Song C', {
    x: 3.8,
    y: 2.0,
    w: 4.1,
    h: 0.18,
    fontSize: 14,
    color: COLORS.text,
    fit: 'shrink',
    margin: 0
  });
  addFlowArrow(slide, 6.2, 2.4, 0, 0.72);
  addCard(slide, { x: 4.0, y: 3.35, w: 4.4, h: 0.95, fill: COLORS.lightBlue });
  slide.addText('更新 User Taste Vector', {
    x: 4.35,
    y: 3.67,
    w: 3.7,
    h: 0.16,
    fontSize: 14,
    bold: true,
    color: COLORS.navy,
    align: 'center',
    margin: 0
  });
  slide.addText('(喜歡: energy↑ R&B↑ acousticness↑)\n(不喜歡: high energy↓ electronic↓)', {
    x: 3.45,
    y: 4.72,
    w: 5.5,
    h: 0.42,
    fontSize: 11,
    color: COLORS.text,
    align: 'center',
    fit: 'shrink',
    margin: 0
  });
  addFlowArrow(slide, 6.2, 4.35, 0, 0.7);
  slide.addText('重新計算候選分數', {
    x: 5.0,
    y: 5.25,
    w: 2.45,
    h: 0.18,
    fontSize: 14,
    bold: true,
    color: COLORS.green,
    align: 'center',
    margin: 0
  });
  addQuote(slide, 'MVP 不需要複雜 ML；只要加權特徵更新，就能展示「Agent 會越用越懂你」。', {
    x: 1.2,
    y: 6.0,
    w: 10.95,
    h: 0.64
  });
  addFooter(slide, 10);
}

// Slide 11
{
  const slide = pptx.addSlide();
  addSectionTag(slide, 'MVP');
  addHeader(slide, 'MVP 範圍與務實取捨', '先驗證核心價值，再逐步擴充整合能力');
  slide.addTable([
    [
      { text: '項目', options: { bold: true, color: COLORS.white, align: 'center' } },
      { text: 'MVP', options: { bold: true, color: COLORS.white, align: 'center' } },
      { text: '未來', options: { bold: true, color: COLORS.white, align: 'center' } }
    ],
    ['Playlist 來源', '公開 Playlist URL', 'Google OAuth / 私人 Playlist / 聆聽紀錄'],
    ['YouTube Quota', '最後驗證步驟才搜尋', '快取 + 批次最佳化'],
    ['回饋學習', '加權特徵向量', '線上學習模型'],
    ['Audio 分析', 'ReccoBeats', '自建分析 / 多來源融合']
  ], {
    x: 0.95,
    y: 1.95,
    w: 11.35,
    h: 2.85,
    border: { type: 'solid', color: COLORS.line, pt: 1 },
    fill: 'FFFFFF',
    color: COLORS.text,
    fontFace: 'Microsoft JhengHei',
    fontSize: 11,
    rowH: 0.52,
    colW: [1.9, 3.0, 5.9],
    autoFit: false,
    align: 'center',
    valign: 'mid',
    margin: 0.03,
    fillHeader: COLORS.navy
  });
  slide.addShape(pptx.ShapeType.roundRect, {
    x: 1.35,
    y: 5.35,
    w: 10.45,
    h: 0.78,
    rectRadius: 0.05,
    line: { color: COLORS.red, transparency: 100 },
    fill: { color: 'FFF6F4' }
  });
  slide.addText('先證明核心價值，不要第一版就卡在帳號整合與複雜基礎設施。', {
    x: 1.7,
    y: 5.63,
    w: 9.75,
    h: 0.16,
    fontSize: 12,
    bold: true,
    color: COLORS.red,
    align: 'center',
    fit: 'shrink',
    margin: 0
  });
  addFooter(slide, 11);
}

// Slide 12
{
  const slide = pptx.addSlide();
  addSectionTag(slide, 'Summary');
  addHeader(slide, '總結', 'Museek 想解決的不是「下一首播什麼」，而是「如何幫你找到值得探索的音樂」');
  slide.addShape(pptx.ShapeType.roundRect, {
    x: 0.95,
    y: 1.65,
    w: 11.35,
    h: 0.82,
    rectRadius: 0.05,
    line: { color: COLORS.lightBlue, transparency: 100 },
    fill: { color: COLORS.lightBlue }
  });
  slide.addText('Museek = 理解需求 × 主動探索 × 客觀分析 × 可解釋推薦', {
    x: 1.25,
    y: 1.95,
    w: 10.75,
    h: 0.18,
    fontSize: 18,
    bold: true,
    color: COLORS.navy,
    align: 'center',
    fit: 'shrink',
    margin: 0
  });
  addBullets(slide, [
    'Discovery Distance 重新定義「冷門」：有關聯，但仍有驚喜',
    'Audio Features 來自客觀資料，不靠 LLM 猜測',
    'Retrieval / Research / Reasoning 三元件分工清楚',
    '確定性驗證擋住幻覺與假連結',
    '回饋迴圈讓 Agent 越用越懂使用者'
  ], { x: 1.15, y: 3.0, w: 6.8, h: 2.5, fontSize: 14 });
  addCard(slide, { x: 8.65, y: 3.15, w: 3.0, h: 2.15, fill: COLORS.white });
  slide.addText('價值主張', {
    x: 9.35,
    y: 3.5,
    w: 1.6,
    h: 0.16,
    fontSize: 10,
    bold: true,
    color: COLORS.navy,
    align: 'center',
    margin: 0
  });
  slide.addText('從\n「被動接受推薦」\n走向\n「主動探索音樂」', {
    x: 9.0,
    y: 3.9,
    w: 2.3,
    h: 1.1,
    fontSize: 16,
    bold: true,
    color: COLORS.text,
    align: 'center',
    valign: 'mid',
    fit: 'shrink',
    margin: 0
  });
  addFooter(slide, 12);
}

pptx.writeFile({ fileName: 'Museek-簡報.pptx' })
  .then(() => {
    console.log('PPTX generated: d:/gitProject/Museek/deck/Museek-簡報.pptx');
  })
  .catch((err) => {
    console.error(err);
    process.exit(1);
  });

const pptxgen = require('pptxgenjs');

const pres = new pptxgen();
pres.layout = 'LAYOUT_WIDE'; // 13.333 x 7.5
pres.author = 'Museek Team';
pres.company = 'Museek';
pres.title = 'Museek 音樂探索 Agent';
pres.lang = 'zh-TW';
pres.theme = {
  headFontFace: 'Microsoft JhengHei',
  bodyFontFace: 'Microsoft JhengHei',
  lang: 'zh-TW'
};

// -- Palette: 深夜聲波 (Midnight Sound) --
const C = {
  bg:        'F7F4EE', // 米色底
  ink:       '1B1230', // 深紫黑
  ink2:      '3A2C5A', // 中紫
  muted:     '6B6480',
  accent:    'E9446A', // 珊瑚玫瑰
  accent2:   'F5B841', // 金
  teal:      '17B8A6', // 綠松
  line:      'E4DED2',
  card:      'FFFFFF',
  darkCard:  '241738',
  chipBg:    'FFE7EC',
  chipBg2:   'FFF3D9',
  chipBg3:   'D9F5F0',
};

const HEAD_FONT = 'Microsoft JhengHei';
const BODY_FONT = 'Microsoft JhengHei';

const SW = 13.333;
const SH = 7.5;

function mkShadow() {
  return { type: 'outer', color: '1B1230', blur: 14, offset: 3, angle: 90, opacity: 0.10 };
}

function pageFooter(slide, idx, total) {
  // Bottom sound-wave decoration bars
  slide.addText('MUSEEK · 音樂探索 Agent', {
    x: 0.5, y: SH - 0.45, w: 6, h: 0.3,
    fontFace: BODY_FONT, fontSize: 9, color: C.muted, charSpacing: 2
  });
  slide.addText(`${String(idx).padStart(2,'0')} / ${String(total).padStart(2,'0')}`, {
    x: SW - 1.6, y: SH - 0.45, w: 1.1, h: 0.3,
    fontFace: BODY_FONT, fontSize: 9, color: C.muted, align: 'right'
  });
  // Small square marker
  slide.addShape(pres.ShapeType.rect, {
    x: SW - 0.55, y: SH - 0.4, w: 0.12, h: 0.12,
    fill: { color: C.accent }, line: { color: C.accent }
  });
}

function pageHeader(slide, kicker) {
  // Left vertical accent
  slide.addShape(pres.ShapeType.rect, {
    x: 0, y: 0.5, w: 0.08, h: 1.1,
    fill: { color: C.accent }, line: { color: C.accent }
  });
  slide.addText(kicker, {
    x: 0.3, y: 0.5, w: 8, h: 0.4,
    fontFace: BODY_FONT, fontSize: 11, bold: true, color: C.accent, charSpacing: 6
  });
}

function pageTitle(slide, title, y = 0.95) {
  slide.addText(title, {
    x: 0.3, y, w: 12.5, h: 0.9,
    fontFace: HEAD_FONT, fontSize: 34, bold: true, color: C.ink, margin: 0
  });
}

function drawSoundWave(slide, x, y, w, h, color, count = 20) {
  const gap = w / count;
  for (let i = 0; i < count; i++) {
    const barH = h * (0.25 + 0.75 * Math.abs(Math.sin(i * 0.9)));
    slide.addShape(pres.ShapeType.rect, {
      x: x + i * gap, y: y + (h - barH),
      w: gap * 0.55, h: barH,
      fill: { color }, line: { color }
    });
  }
}

const TOTAL = 12;

// ---------- Slide 1: Cover ----------
{
  const s = pres.addSlide();
  s.background = { color: C.ink };

  // Dotted background pattern (simple decorative dots)
  for (let r = 0; r < 6; r++) {
    for (let c = 0; c < 10; c++) {
      s.addShape(pres.ShapeType.ellipse, {
        x: 7 + c * 0.55, y: 0.6 + r * 0.55, w: 0.06, h: 0.06,
        fill: { color: C.accent2, transparency: 60 },
        line: { color: C.accent2, transparency: 60 }
      });
    }
  }

  // Accent horizontal line
  s.addShape(pres.ShapeType.rect, {
    x: 0.7, y: 1.2, w: 0.9, h: 0.06,
    fill: { color: C.accent }, line: { color: C.accent }
  });

  s.addText('MUSEEK · 2026', {
    x: 0.7, y: 0.7, w: 6, h: 0.4,
    fontFace: BODY_FONT, fontSize: 12, bold: true, color: C.accent2, charSpacing: 8
  });

  s.addText('Museek', {
    x: 0.6, y: 1.8, w: 10, h: 1.6,
    fontFace: HEAD_FONT, fontSize: 96, bold: true, color: 'FFFFFF', margin: 0
  });

  s.addText('你的音樂探索夥伴，而不只是推薦引擎', {
    x: 0.7, y: 3.4, w: 12, h: 0.6,
    fontFace: HEAD_FONT, fontSize: 24, color: C.accent2, margin: 0
  });

  // Quote block
  s.addShape(pres.ShapeType.rect, {
    x: 0.7, y: 4.5, w: 0.06, h: 1.5,
    fill: { color: C.accent }, line: { color: C.accent }
  });
  s.addText('用一句話描述心情，Agent 主動探索、分析、\n並解釋「為什麼你會喜歡」。', {
    x: 1.0, y: 4.55, w: 9, h: 1.4,
    fontFace: HEAD_FONT, fontSize: 20, italic: true, color: 'FFFFFF',
    paraSpaceAfter: 6
  });

  // Sound wave decoration bottom
  drawSoundWave(s, 0.7, 6.4, 6.5, 0.7, C.accent, 26);

  s.addText('LLM  ·  AI Agent  ·  Music API  ·  Web Search  ·  Audio Analysis', {
    x: 7.5, y: 6.5, w: 5.5, h: 0.4,
    fontFace: BODY_FONT, fontSize: 10, color: C.accent2, align: 'right', charSpacing: 2
  });
}

// ---------- Slide 2: 問題動機 ----------
{
  const s = pres.addSlide();
  s.background = { color: C.bg };
  pageHeader(s, 'PROBLEM · 問題動機');
  pageTitle(s, '現有串流推薦的盲點');

  // Left: three point cards
  const items = [
    { n: '01', title: '只擅長「更多相似」', body: '推薦系統精於相似，但不擅長主動探索。' },
    { n: '02', title: '跳出舒適圈仍要自己來', body: '想拓展品味時，還是得手動搜尋、篩選。' },
    { n: '03', title: '自然語言需求難以表達', body: '真實情境往往帶有「氛圍」「情緒」「冷門」等抽象條件。' },
  ];

  items.forEach((it, i) => {
    const x = 0.4;
    const y = 2.0 + i * 1.35;
    s.addShape(pres.ShapeType.rect, {
      x, y, w: 6.8, h: 1.15,
      fill: { color: C.card }, line: { color: C.line, width: 1 },
      shadow: mkShadow()
    });
    // number bar
    s.addShape(pres.ShapeType.rect, {
      x, y, w: 0.12, h: 1.15,
      fill: { color: C.accent }, line: { color: C.accent }
    });
    s.addText(it.n, {
      x: x + 0.25, y: y + 0.1, w: 0.7, h: 0.4,
      fontFace: HEAD_FONT, fontSize: 14, bold: true, color: C.accent
    });
    s.addText(it.title, {
      x: x + 0.9, y: y + 0.1, w: 5.7, h: 0.4,
      fontFace: HEAD_FONT, fontSize: 18, bold: true, color: C.ink, margin: 0
    });
    s.addText(it.body, {
      x: x + 0.9, y: y + 0.55, w: 5.7, h: 0.55,
      fontFace: BODY_FONT, fontSize: 12, color: C.muted, margin: 0
    });
  });

  // Right: quoted "real user need"
  s.addShape(pres.ShapeType.rect, {
    x: 7.6, y: 2.0, w: 5.3, h: 4.05,
    fill: { color: C.darkCard }, line: { color: C.darkCard },
    shadow: mkShadow()
  });
  s.addText('真實需求聽起來像這樣', {
    x: 7.85, y: 2.2, w: 5, h: 0.4,
    fontFace: BODY_FONT, fontSize: 11, color: C.accent2, charSpacing: 4, bold: true
  });
  s.addText('「', {
    x: 7.85, y: 2.55, w: 1, h: 1.2,
    fontFace: HEAD_FONT, fontSize: 90, color: C.accent, bold: true
  });
  s.addText('我最近很喜歡 XXX，想找沒聽過、\n比較冷門、但氛圍相近的音樂。', {
    x: 7.85, y: 3.55, w: 4.9, h: 1.6,
    fontFace: HEAD_FONT, fontSize: 20, color: 'FFFFFF', italic: true,
    paraSpaceAfter: 6
  });
  s.addText('傳統搜尋 / 推薦系統無法承接這種自然語言需求。', {
    x: 7.85, y: 5.35, w: 4.9, h: 0.5,
    fontFace: BODY_FONT, fontSize: 12, color: C.accent2
  });

  pageFooter(s, 2, TOTAL);
}

// ---------- Slide 3: 我們的主張 ----------
{
  const s = pres.addSlide();
  s.background = { color: C.bg };
  pageHeader(s, 'PROPOSITION · 我們的主張');
  pageTitle(s, '讓 AI 不只是「推薦歌曲」');

  // Big statement
  s.addShape(pres.ShapeType.rect, {
    x: 0.4, y: 2.0, w: 12.5, h: 1.9,
    fill: { color: C.darkCard }, line: { color: C.darkCard }, shadow: mkShadow()
  });
  s.addShape(pres.ShapeType.rect, {
    x: 0.4, y: 2.0, w: 0.15, h: 1.9,
    fill: { color: C.accent2 }, line: { color: C.accent2 }
  });
  s.addText([
    { text: '能', options: { color: 'FFFFFF' } },
    { text: '理解需求 ', options: { color: C.accent2, bold: true } },
    { text: '→ ', options: { color: 'FFFFFF' } },
    { text: '主動探索 ', options: { color: C.accent2, bold: true } },
    { text: '→ ', options: { color: 'FFFFFF' } },
    { text: '客觀分析 ', options: { color: C.accent2, bold: true } },
    { text: '→ ', options: { color: 'FFFFFF' } },
    { text: '解釋理由', options: { color: C.accent2, bold: true } },
    { text: '\n的音樂探索夥伴。', options: { color: 'FFFFFF' } },
  ], {
    x: 0.9, y: 2.15, w: 11.8, h: 1.6,
    fontFace: HEAD_FONT, fontSize: 32, bold: true, margin: 0,
    paraSpaceAfter: 8
  });

  // Core stack chips
  s.addText('核心組合', {
    x: 0.4, y: 4.3, w: 6, h: 0.4,
    fontFace: BODY_FONT, fontSize: 12, color: C.accent, bold: true, charSpacing: 4
  });

  const stack = [
    { t: 'LLM',          bg: C.chipBg,  fg: C.accent },
    { t: 'AI Agent',     bg: C.chipBg2, fg: 'B27B00' },
    { t: 'Music API',    bg: C.chipBg3, fg: '0F8577' },
    { t: 'Web Search',   bg: C.chipBg,  fg: C.accent },
    { t: 'Audio Analysis', bg: C.chipBg2, fg: 'B27B00' },
    { t: '個人化資料',    bg: C.chipBg3, fg: '0F8577' },
  ];

  let cx = 0.4;
  const cy = 4.85;
  stack.forEach((it) => {
    const w = 0.55 + it.t.length * 0.28;
    s.addShape(pres.ShapeType.roundRect, {
      x: cx, y: cy, w, h: 0.7,
      fill: { color: it.bg }, line: { color: it.bg }, rectRadius: 0.15
    });
    s.addText(it.t, {
      x: cx, y: cy, w, h: 0.7,
      fontFace: HEAD_FONT, fontSize: 16, bold: true, color: it.fg,
      align: 'center', valign: 'middle', margin: 0
    });
    cx += w + 0.25;
  });

  // decorative sound wave
  drawSoundWave(s, 0.4, 6.15, 12.5, 0.5, C.accent, 40);

  pageFooter(s, 3, TOTAL);
}

// ---------- Slide 4: Discovery Distance ----------
{
  const s = pres.addSlide();
  s.background = { color: C.bg };
  pageHeader(s, 'CORE VALUE · 核心差異化');
  pageTitle(s, 'Discovery Distance — 探索距離');

  // Left card: statement
  s.addShape(pres.ShapeType.rect, {
    x: 0.4, y: 1.95, w: 6.0, h: 2.1,
    fill: { color: C.card }, line: { color: C.line, width: 1 }, shadow: mkShadow()
  });
  s.addShape(pres.ShapeType.rect, {
    x: 0.4, y: 1.95, w: 0.12, h: 2.1,
    fill: { color: C.accent }, line: { color: C.accent }
  });
  s.addText('「冷門」不等於「沒聽過」', {
    x: 0.7, y: 2.05, w: 5.6, h: 0.5,
    fontFace: HEAD_FONT, fontSize: 20, bold: true, color: C.ink, margin: 0
  });
  s.addText('而是——跟你的品味有關聯，\n但沒近到只是換一首相似歌。', {
    x: 0.7, y: 2.6, w: 5.6, h: 1.3,
    fontFace: HEAD_FONT, fontSize: 16, color: C.ink2, italic: true, margin: 0
  });

  // Formula card
  s.addShape(pres.ShapeType.rect, {
    x: 0.4, y: 4.2, w: 6.0, h: 1.5,
    fill: { color: C.darkCard }, line: { color: C.darkCard }, shadow: mkShadow()
  });
  s.addText('Discovery Score', {
    x: 0.7, y: 4.3, w: 5, h: 0.35,
    fontFace: BODY_FONT, fontSize: 11, bold: true, color: C.accent2, charSpacing: 3
  });
  s.addText([
    { text: 'Similarity', options: { color: 'FFFFFF', bold: true } },
    { text: '  ×  ', options: { color: C.accent } },
    { text: 'Familiarity Distance', options: { color: 'FFFFFF', bold: true } },
    { text: '  ×  ', options: { color: C.accent } },
    { text: 'Popularity Factor', options: { color: 'FFFFFF', bold: true } },
  ], {
    x: 0.7, y: 4.7, w: 5.6, h: 0.95,
    fontFace: HEAD_FONT, fontSize: 16, margin: 0
  });

  // Right: table
  const rows = [
    [{ t: 'Song', h: true }, { t: '相似度', h: true }, { t: '熟悉度距離', h: true }, { t: '熱門度', h: true }, { t: 'Discovery', h: true }],
    [{ t: 'A' }, { t: '0.95' }, { t: '近' }, { t: '高' }, { t: '低', dim: true }],
    [{ t: 'B', hi: true }, { t: '0.82', hi: true }, { t: '中', hi: true }, { t: '中', hi: true }, { t: '★ 高', hi: true }],
    [{ t: 'C' }, { t: '0.65' }, { t: '遠' }, { t: '低' }, { t: '中' }],
    [{ t: 'D' }, { t: '0.30' }, { t: '極遠' }, { t: '低' }, { t: '低', dim: true }],
  ];

  const tableData = rows.map((row) => row.map((cell) => {
    if (cell.h) {
      return { text: cell.t, options: { fill: { color: C.ink }, color: C.accent2, bold: true, align: 'center', valign: 'middle', fontFace: HEAD_FONT, fontSize: 12 } };
    }
    if (cell.hi) {
      return { text: cell.t, options: { fill: { color: 'FFE7EC' }, color: C.accent, bold: true, align: 'center', valign: 'middle', fontFace: HEAD_FONT, fontSize: 14 } };
    }
    if (cell.dim) {
      return { text: cell.t, options: { color: C.muted, align: 'center', valign: 'middle', fontFace: BODY_FONT, fontSize: 12 } };
    }
    return { text: cell.t, options: { color: C.ink, align: 'center', valign: 'middle', fontFace: BODY_FONT, fontSize: 12 } };
  }));

  s.addTable(tableData, {
    x: 6.8, y: 1.95, w: 6.15, colW: [0.9, 1.15, 1.4, 1.15, 1.55],
    rowH: [0.5, 0.55, 0.65, 0.55, 0.55],
    border: { pt: 1, color: C.line }
  });

  // Bottom conclusion
  s.addShape(pres.ShapeType.rect, {
    x: 0.4, y: 6.15, w: 12.5, h: 0.75,
    fill: { color: C.accent }, line: { color: C.accent }
  });
  s.addText('這就是 Museek 的核心價值 — 讓推薦「有關聯，也有驚喜」。', {
    x: 0.4, y: 6.15, w: 12.5, h: 0.75,
    fontFace: HEAD_FONT, fontSize: 18, bold: true, color: 'FFFFFF',
    align: 'center', valign: 'middle', margin: 0
  });

  pageFooter(s, 4, TOTAL);
}

// ---------- Slide 5: System Architecture ----------
{
  const s = pres.addSlide();
  s.background = { color: C.bg };
  pageHeader(s, 'ARCHITECTURE · 系統架構');
  pageTitle(s, 'Museek Agent 協調三種能力');

  // Node helper
  const box = (x, y, w, h, title, subtitle, opts = {}) => {
    const fill = opts.fill || C.card;
    const stroke = opts.stroke || C.line;
    const tColor = opts.tColor || C.ink;
    const sColor = opts.sColor || C.muted;
    s.addShape(pres.ShapeType.rect, {
      x, y, w, h, fill: { color: fill }, line: { color: stroke, width: 1 }, shadow: mkShadow()
    });
    if (opts.bar) {
      s.addShape(pres.ShapeType.rect, {
        x, y, w: 0.1, h,
        fill: { color: opts.bar }, line: { color: opts.bar }
      });
    }
    s.addText(title, {
      x: x + 0.2, y: y + 0.1, w: w - 0.3, h: 0.4,
      fontFace: HEAD_FONT, fontSize: 13, bold: true, color: tColor, margin: 0
    });
    if (subtitle) {
      s.addText(subtitle, {
        x: x + 0.2, y: y + 0.5, w: w - 0.3, h: h - 0.55,
        fontFace: BODY_FONT, fontSize: 10, color: sColor, margin: 0
      });
    }
  };

  const arrow = (x1, y1, x2, y2) => {
    s.addShape(pres.ShapeType.line, {
      x: x1, y: y1, w: x2 - x1, h: y2 - y1,
      line: { color: C.ink2, width: 1.5, endArrowType: 'triangle' }
    });
  };

  // Top: User input
  box(4.8, 1.85, 3.7, 0.75, '👤 使用者自然語言需求', '一句話描述心情、情境', {
    fill: C.darkCard, stroke: C.darkCard, tColor: 'FFFFFF', sColor: C.accent2
  });
  arrow(6.65, 2.6, 6.65, 3.0);

  // Center: orchestrator
  box(4.3, 3.0, 4.7, 0.9, '🎼 Museek Agent 協調器', 'LLM 拆解需求並分配到子工具', {
    fill: C.accent, stroke: C.accent, tColor: 'FFFFFF', sColor: 'FFE7EC'
  });

  // Three parallel tools
  const y1 = 4.3;
  box(0.5, y1, 3.6, 1.0, '🔎 Music Search Tool', 'YouTube + ReccoBeats\n找 track / artist / playlist', { bar: C.teal });
  box(4.8, y1, 3.6, 1.0, '📰 Web Research Tool', '風格 / 樂評 / 社群訪談\n補足文化脈絡', { bar: C.accent2 });
  box(9.1, y1, 3.6, 1.0, '🧠 Reasoning Agent', '推導客觀推薦理由\nExplain why you\'ll like it', { bar: C.accent });

  arrow(5.5, 3.9, 2.3, 4.3);
  arrow(6.65, 3.9, 6.6, 4.3);
  arrow(7.8, 3.9, 10.9, 4.3);

  // Ranking + Verification
  box(1.5, 5.6, 4.5, 0.85, '📊 Discovery Ranking', '依 Similarity × Familiarity × Popularity 排序', { bar: C.teal });
  box(7.3, 5.6, 4.5, 0.85, '✅ 程式層 videoId 驗證', 'YouTube API 實際搜尋，過濾幻覺', { bar: C.accent });
  arrow(2.3, 5.3, 3.7, 5.6);
  arrow(10.9, 5.3, 9.5, 5.6);
  arrow(6.0, 6.03, 7.3, 6.03);

  // Player + feedback
  box(4.3, 6.75, 4.7, 0.55, '🎧 前端播放器 → 使用者評分回饋 ↺', '', {
    fill: C.darkCard, stroke: C.darkCard, tColor: 'FFFFFF'
  });
  arrow(9.5, 6.45, 8.9, 6.75);
  arrow(3.7, 6.45, 4.5, 6.75);

  pageFooter(s, 5, TOTAL);
}

// ---------- Slide 6: 三個核心元件 ----------
{
  const s = pres.addSlide();
  s.background = { color: C.bg };
  pageHeader(s, 'COMPONENTS · 三大元件');
  pageTitle(s, '職責清楚、不重疊');

  const comps = [
    { t: 'Music Search Tool',   sub: 'Music Retrieval',
      body: '負責找 track / artist / album，\n取得 playlist、驗證 video。',
      color: C.teal, chip: 'Retrieval', chipBg: C.chipBg3, chipFg: '0F8577', icon: '🔎' },
    { t: 'Web Research Tool',   sub: 'Music Research',
      body: '查藝人風格、訪談、樂評、\n社群討論等文化脈絡。',
      color: C.accent2, chip: 'Research', chipBg: C.chipBg2, chipFg: 'B27B00', icon: '📰' },
    { t: 'Reasoning Agent',     sub: 'Recommendation Reasoning',
      body: '依客觀 audio features 推導\n「為什麼這首歌適合你」。',
      color: C.accent, chip: 'Reasoning', chipBg: C.chipBg, chipFg: C.accent, icon: '🧠' },
  ];

  comps.forEach((c, i) => {
    const x = 0.4 + i * 4.35;
    const y = 2.0;
    const w = 4.15;
    const h = 3.7;
    s.addShape(pres.ShapeType.rect, {
      x, y, w, h, fill: { color: C.card }, line: { color: C.line, width: 1 }, shadow: mkShadow()
    });
    // top color band
    s.addShape(pres.ShapeType.rect, {
      x, y, w, h: 0.15, fill: { color: c.color }, line: { color: c.color }
    });
    // icon
    s.addText(c.icon, {
      x: x + 0.3, y: y + 0.35, w: 1.2, h: 1.0,
      fontFace: HEAD_FONT, fontSize: 44
    });
    // chip
    s.addShape(pres.ShapeType.roundRect, {
      x: x + 0.3, y: y + 1.4, w: 1.5, h: 0.4,
      fill: { color: c.chipBg }, line: { color: c.chipBg }, rectRadius: 0.1
    });
    s.addText(c.chip, {
      x: x + 0.3, y: y + 1.4, w: 1.5, h: 0.4,
      fontFace: HEAD_FONT, fontSize: 11, bold: true, color: c.chipFg,
      align: 'center', valign: 'middle', margin: 0, charSpacing: 2
    });
    s.addText(c.t, {
      x: x + 0.3, y: y + 1.9, w: w - 0.5, h: 0.5,
      fontFace: HEAD_FONT, fontSize: 20, bold: true, color: C.ink, margin: 0
    });
    s.addText(c.sub, {
      x: x + 0.3, y: y + 2.4, w: w - 0.5, h: 0.35,
      fontFace: BODY_FONT, fontSize: 11, color: c.color, bold: true, charSpacing: 2
    });
    s.addText(c.body, {
      x: x + 0.3, y: y + 2.85, w: w - 0.5, h: 0.85,
      fontFace: BODY_FONT, fontSize: 12, color: C.muted, margin: 0
    });
  });

  // Bottom takeaway
  s.addShape(pres.ShapeType.rect, {
    x: 0.4, y: 6.15, w: 12.5, h: 0.75,
    fill: { color: C.darkCard }, line: { color: C.darkCard }
  });
  s.addText([
    { text: '不是 ', options: { color: 'FFFFFF' } },
    { text: 'Search A vs Search B', options: { color: C.accent2, bold: true } },
    { text: '，而是 ', options: { color: 'FFFFFF' } },
    { text: 'Retrieval vs Research vs Reasoning', options: { color: C.accent2, bold: true } },
    { text: '。', options: { color: 'FFFFFF' } },
  ], {
    x: 0.4, y: 6.15, w: 12.5, h: 0.75,
    fontFace: HEAD_FONT, fontSize: 17, align: 'center', valign: 'middle', margin: 0
  });

  pageFooter(s, 6, TOTAL);
}

// ---------- Slide 7: Data Pipeline ----------
{
  const s = pres.addSlide();
  s.background = { color: C.bg };
  pageHeader(s, 'PIPELINE · 資料流');
  pageTitle(s, '從 Playlist 到 Top 5 推薦');

  const steps = [
    { n: '01', t: '使用者 Playlist',     b: '公開 URL 輸入' },
    { n: '02', t: '一次取 items + Cache', b: '避免重複請求' },
    { n: '03', t: 'Taste Profile',       b: '建立品味向量' },
    { n: '04', t: 'ReccoBeats 找候選',    b: '30 首 candidate' },
    { n: '05', t: 'Discovery Ranking',   b: '重排 Top 8' },
    { n: '06', t: 'YouTube 驗證',        b: '取有效 videoId' },
    { n: '07', t: 'Top 5 推薦',          b: '呈現給使用者' },
  ];

  const startX = 0.4;
  const startY = 2.0;
  const boxW = 1.75;
  const boxH = 1.5;
  const gap = 0.05;
  const totalW = steps.length * boxW + (steps.length - 1) * gap;
  const offsetX = (SW - totalW) / 2;

  steps.forEach((st, i) => {
    const x = offsetX + i * (boxW + gap);
    const y = startY;
    s.addShape(pres.ShapeType.rect, {
      x, y, w: boxW, h: boxH,
      fill: { color: C.card }, line: { color: C.line, width: 1 }, shadow: mkShadow()
    });
    s.addShape(pres.ShapeType.rect, {
      x, y, w: boxW, h: 0.35, fill: { color: C.ink }, line: { color: C.ink }
    });
    s.addText(st.n, {
      x, y, w: boxW, h: 0.35,
      fontFace: HEAD_FONT, fontSize: 12, bold: true, color: C.accent2,
      align: 'center', valign: 'middle', margin: 0, charSpacing: 3
    });
    s.addText(st.t, {
      x: x + 0.1, y: y + 0.5, w: boxW - 0.2, h: 0.55,
      fontFace: HEAD_FONT, fontSize: 12, bold: true, color: C.ink,
      align: 'center', margin: 0
    });
    s.addText(st.b, {
      x: x + 0.1, y: y + 1.05, w: boxW - 0.2, h: 0.4,
      fontFace: BODY_FONT, fontSize: 10, color: C.muted,
      align: 'center', margin: 0
    });

    // arrow
    if (i < steps.length - 1) {
      const ax = x + boxW;
      const ay = y + boxH / 2;
      s.addShape(pres.ShapeType.rtTriangle, {
        x: ax - 0.02, y: ay - 0.08, w: 0.12, h: 0.16,
        fill: { color: C.accent }, line: { color: C.accent }, rotate: 90
      });
    }
  });

  // Audio features section
  s.addShape(pres.ShapeType.rect, {
    x: 0.4, y: 4.15, w: 12.5, h: 2.6,
    fill: { color: C.card }, line: { color: C.line, width: 1 }, shadow: mkShadow()
  });
  s.addShape(pres.ShapeType.rect, {
    x: 0.4, y: 4.15, w: 0.15, h: 2.6,
    fill: { color: C.teal }, line: { color: C.teal }
  });
  s.addText('Audio Features 來源', {
    x: 0.7, y: 4.25, w: 6, h: 0.35,
    fontFace: BODY_FONT, fontSize: 11, bold: true, color: C.teal, charSpacing: 3
  });
  s.addText('ReccoBeats · 免費、免 API Key', {
    x: 0.7, y: 4.6, w: 12, h: 0.5,
    fontFace: HEAD_FONT, fontSize: 22, bold: true, color: C.ink, margin: 0
  });

  const features = ['tempo', 'energy', 'danceability', 'valence', 'acousticness', 'instrumentalness', 'liveness', 'loudness', 'speechiness'];
  features.forEach((f, i) => {
    const col = i % 5;
    const row = Math.floor(i / 5);
    const fx = 0.75 + col * 2.4;
    const fy = 5.25 + row * 0.55;
    s.addShape(pres.ShapeType.roundRect, {
      x: fx, y: fy, w: 2.25, h: 0.42,
      fill: { color: C.chipBg3 }, line: { color: C.chipBg3 }, rectRadius: 0.08
    });
    s.addText(f, {
      x: fx, y: fy, w: 2.25, h: 0.42,
      fontFace: 'Consolas', fontSize: 12, color: '0F8577', bold: true,
      align: 'center', valign: 'middle', margin: 0
    });
  });

  s.addText('不讓 LLM 猜 BPM，一切基於客觀數據。', {
    x: 0.7, y: 6.4, w: 12, h: 0.3,
    fontFace: HEAD_FONT, fontSize: 12, italic: true, color: C.accent, bold: true
  });

  pageFooter(s, 7, TOTAL);
}

// ---------- Slide 8: Reasoning Agent ----------
{
  const s = pres.addSlide();
  s.background = { color: C.bg };
  pageHeader(s, 'REASONING · 有根據的解釋');
  pageTitle(s, 'Reasoning Agent 如何「不亂掰」');

  // Left: input JSON
  s.addShape(pres.ShapeType.rect, {
    x: 0.4, y: 2.0, w: 6.2, h: 4.3,
    fill: { color: C.darkCard }, line: { color: C.darkCard }, shadow: mkShadow()
  });
  s.addText('INPUT · 客觀資料', {
    x: 0.65, y: 2.15, w: 5.5, h: 0.35,
    fontFace: BODY_FONT, fontSize: 11, bold: true, color: C.accent2, charSpacing: 3
  });

  const json = [
    { text: '{\n', options: { color: 'E4DED2' } },
    { text: '  "user_profile": {\n', options: { color: 'FFFFFF' } },
    { text: '    "avg_energy": ', options: { color: 'E4DED2' } },
    { text: '0.42', options: { color: C.accent2, bold: true } },
    { text: ',\n', options: { color: 'E4DED2' } },
    { text: '    "avg_valence": ', options: { color: 'E4DED2' } },
    { text: '0.51', options: { color: C.accent2, bold: true } },
    { text: ',\n', options: { color: 'E4DED2' } },
    { text: '    "favorite_genres": [', options: { color: 'E4DED2' } },
    { text: '"R&B"', options: { color: C.teal } },
    { text: ', ', options: { color: 'E4DED2' } },
    { text: '"Neo Soul"', options: { color: C.teal } },
    { text: ']\n  },\n', options: { color: 'E4DED2' } },
    { text: '  "candidate": {\n', options: { color: 'FFFFFF' } },
    { text: '    "energy": ', options: { color: 'E4DED2' } },
    { text: '0.45', options: { color: C.accent, bold: true } },
    { text: ',\n', options: { color: 'E4DED2' } },
    { text: '    "valence": ', options: { color: 'E4DED2' } },
    { text: '0.55', options: { color: C.accent, bold: true } },
    { text: ',\n', options: { color: 'E4DED2' } },
    { text: '    "acousticness": ', options: { color: 'E4DED2' } },
    { text: '0.72', options: { color: C.accent, bold: true } },
    { text: ',\n', options: { color: 'E4DED2' } },
    { text: '    "tempo": ', options: { color: 'E4DED2' } },
    { text: '82', options: { color: C.accent, bold: true } },
    { text: '\n  }\n}', options: { color: 'E4DED2' } },
  ];
  s.addText(json, {
    x: 0.65, y: 2.55, w: 5.7, h: 3.6,
    fontFace: 'Consolas', fontSize: 13, margin: 0
  });

  // Arrow between
  s.addShape(pres.ShapeType.rtTriangle, {
    x: 6.75, y: 4.0, w: 0.3, h: 0.4,
    fill: { color: C.accent }, line: { color: C.accent }, rotate: 90
  });

  // Right: output explanation
  s.addShape(pres.ShapeType.rect, {
    x: 7.2, y: 2.0, w: 5.7, h: 4.3,
    fill: { color: C.card }, line: { color: C.line, width: 1 }, shadow: mkShadow()
  });
  s.addShape(pres.ShapeType.rect, {
    x: 7.2, y: 2.0, w: 0.15, h: 4.3,
    fill: { color: C.accent }, line: { color: C.accent }
  });
  s.addText('OUTPUT · 有根據的解釋', {
    x: 7.45, y: 2.15, w: 5.2, h: 0.35,
    fontFace: BODY_FONT, fontSize: 11, bold: true, color: C.accent, charSpacing: 3
  });

  s.addText('「', {
    x: 7.45, y: 2.35, w: 1, h: 1.0,
    fontFace: HEAD_FONT, fontSize: 60, color: C.accent, bold: true
  });
  s.addText([
    { text: '這首歌的 ', options: { color: C.ink } },
    { text: 'Energy、Valence ', options: { color: C.accent, bold: true } },
    { text: '與你偏好接近，但 ', options: { color: C.ink } },
    { text: 'Acousticness ', options: { color: C.teal, bold: true } },
    { text: '更高，符合你想探索\n', options: { color: C.ink } },
    { text: '更溫暖、自然音色', options: { color: C.accent, bold: true, italic: true } },
    { text: ' 的需求。', options: { color: C.ink } },
  ], {
    x: 7.45, y: 3.35, w: 5.3, h: 2.5,
    fontFace: HEAD_FONT, fontSize: 17, margin: 0, paraSpaceAfter: 6
  });

  pageFooter(s, 8, TOTAL);
}

// ---------- Slide 9: 安全設計 ----------
{
  const s = pres.addSlide();
  s.background = { color: C.bg };
  pageHeader(s, 'SAFETY · 幻覺防護');
  pageTitle(s, 'AI 輸出 → 確定性驗證');

  // Two panels
  // Left: PROBLEM
  s.addShape(pres.ShapeType.rect, {
    x: 0.4, y: 2.0, w: 5.7, h: 4.1,
    fill: { color: C.card }, line: { color: C.line, width: 1 }, shadow: mkShadow()
  });
  s.addShape(pres.ShapeType.rect, {
    x: 0.4, y: 2.0, w: 5.7, h: 0.5,
    fill: { color: C.accent }, line: { color: C.accent }
  });
  s.addText('⚠️ PROBLEM · 問題', {
    x: 0.6, y: 2.0, w: 5.4, h: 0.5,
    fontFace: HEAD_FONT, fontSize: 13, bold: true, color: 'FFFFFF',
    valign: 'middle', margin: 0, charSpacing: 3
  });
  s.addText('LLM 會幻覺出不存在的歌，\n並附上看似合理的假連結。', {
    x: 0.6, y: 2.7, w: 5.4, h: 1.2,
    fontFace: HEAD_FONT, fontSize: 20, bold: true, color: C.ink, margin: 0
  });
  s.addText([
    { text: '· 產生 fake YouTube ID\n', options: { breakLine: false } },
    { text: '· 引用不存在的專輯 / 藝人\n', options: { breakLine: false } },
    { text: '· 若直接送到前端 → 播不出、體驗崩壞', options: { breakLine: false } },
  ], {
    x: 0.6, y: 4.0, w: 5.4, h: 1.9,
    fontFace: BODY_FONT, fontSize: 13, color: C.muted, margin: 0,
    paraSpaceAfter: 6
  });

  // Right: SOLUTION
  s.addShape(pres.ShapeType.rect, {
    x: 7.2, y: 2.0, w: 5.7, h: 4.1,
    fill: { color: C.darkCard }, line: { color: C.darkCard }, shadow: mkShadow()
  });
  s.addShape(pres.ShapeType.rect, {
    x: 7.2, y: 2.0, w: 5.7, h: 0.5,
    fill: { color: C.teal }, line: { color: C.teal }
  });
  s.addText('✅ SOLUTION · 做法', {
    x: 7.4, y: 2.0, w: 5.4, h: 0.5,
    fontFace: HEAD_FONT, fontSize: 13, bold: true, color: 'FFFFFF',
    valign: 'middle', margin: 0, charSpacing: 3
  });
  s.addText('不靠 prompt 限制，\n靠程式驗證。', {
    x: 7.4, y: 2.7, w: 5.4, h: 1.2,
    fontFace: HEAD_FONT, fontSize: 20, bold: true, color: 'FFFFFF', margin: 0
  });

  // Flow steps in right panel
  const flow = [
    { t: 'LLM 只輸出', v: 'title + artist', color: C.accent2 },
    { t: '後端呼叫',   v: 'YouTube API 實際搜尋', color: C.accent2 },
    { t: '查不到?',   v: '直接丟棄', color: C.accent },
    { t: '播放器只吃', v: '驗證過的 videoId', color: C.teal },
  ];
  flow.forEach((f, i) => {
    const fy = 4.0 + i * 0.5;
    s.addShape(pres.ShapeType.ellipse, {
      x: 7.4, y: fy, w: 0.28, h: 0.28,
      fill: { color: f.color }, line: { color: f.color }
    });
    s.addText(String(i + 1), {
      x: 7.4, y: fy, w: 0.28, h: 0.28,
      fontFace: HEAD_FONT, fontSize: 10, bold: true, color: C.ink,
      align: 'center', valign: 'middle', margin: 0
    });
    s.addText([
      { text: f.t + ' ', options: { color: 'FFFFFF' } },
      { text: f.v, options: { color: f.color, bold: true } },
    ], {
      x: 7.8, y: fy - 0.02, w: 5.0, h: 0.35,
      fontFace: BODY_FONT, fontSize: 13, margin: 0
    });
  });

  // Bottom emphasis
  s.addShape(pres.ShapeType.rect, {
    x: 0.4, y: 6.3, w: 12.5, h: 0.6,
    fill: { color: C.ink }, line: { color: C.ink }
  });
  s.addText([
    { text: '絕不讓 LLM 直接生成 URL — ', options: { color: C.accent2, bold: true } },
    { text: '幻覺歌曲會在驗證步驟被自動過濾。', options: { color: 'FFFFFF' } },
  ], {
    x: 0.4, y: 6.3, w: 12.5, h: 0.6,
    fontFace: HEAD_FONT, fontSize: 15, align: 'center', valign: 'middle', margin: 0
  });

  pageFooter(s, 9, TOTAL);
}

// ---------- Slide 10: Feedback Loop ----------
{
  const s = pres.addSlide();
  s.background = { color: C.bg };
  pageHeader(s, 'FEEDBACK · 回饋學習迴圈');
  pageTitle(s, '評分不是裝飾，會直接影響下一輪');

  // Circular flow with 4 boxes horizontally
  const stages = [
    { icon: '🎧', t: 'Museek 推薦 5 首', b: '呈現初始清單' },
    { icon: '👍👎', t: '使用者評分', b: 'Song A ✓  B ✗  C ✓' },
    { icon: '📈', t: '更新 Taste Vector', b: 'energy↑ R&B↑\nhigh energy↓' },
    { icon: '🔁', t: '重新計算候選', b: '下一輪更懂你' },
  ];

  stages.forEach((st, i) => {
    const x = 0.4 + i * 3.25;
    const y = 2.1;
    const w = 2.95;
    const h = 2.4;
    s.addShape(pres.ShapeType.rect, {
      x, y, w, h, fill: { color: C.card }, line: { color: C.line, width: 1 }, shadow: mkShadow()
    });
    // Number circle
    s.addShape(pres.ShapeType.ellipse, {
      x: x + w / 2 - 0.25, y: y - 0.28, w: 0.5, h: 0.5,
      fill: { color: C.accent }, line: { color: C.accent }
    });
    s.addText(String(i + 1), {
      x: x + w / 2 - 0.25, y: y - 0.28, w: 0.5, h: 0.5,
      fontFace: HEAD_FONT, fontSize: 16, bold: true, color: 'FFFFFF',
      align: 'center', valign: 'middle', margin: 0
    });
    s.addText(st.icon, {
      x, y: y + 0.35, w, h: 0.7,
      fontFace: HEAD_FONT, fontSize: 32, align: 'center', margin: 0
    });
    s.addText(st.t, {
      x: x + 0.15, y: y + 1.15, w: w - 0.3, h: 0.45,
      fontFace: HEAD_FONT, fontSize: 14, bold: true, color: C.ink,
      align: 'center', margin: 0
    });
    s.addText(st.b, {
      x: x + 0.15, y: y + 1.6, w: w - 0.3, h: 0.7,
      fontFace: BODY_FONT, fontSize: 11, color: C.muted,
      align: 'center', margin: 0
    });

    // Arrow
    if (i < stages.length - 1) {
      s.addShape(pres.ShapeType.rtTriangle, {
        x: x + w + 0.02, y: y + h / 2 - 0.1, w: 0.2, h: 0.22,
        fill: { color: C.accent2 }, line: { color: C.accent2 }, rotate: 90
      });
    }
  });

  // Loop arrow back
  s.addShape(pres.ShapeType.line, {
    x: 12.75, y: 4.5, w: 0, h: 0.6,
    line: { color: C.accent2, width: 2 }
  });
  s.addShape(pres.ShapeType.line, {
    x: 0.55, y: 5.1, w: 12.2, h: 0,
    line: { color: C.accent2, width: 2, endArrowType: 'triangle', beginArrowType: 'none' }
  });
  s.addShape(pres.ShapeType.line, {
    x: 0.55, y: 4.5, w: 0, h: 0.6,
    line: { color: C.accent2, width: 2 }
  });
  s.addText('LOOP', {
    x: 5.5, y: 5.15, w: 2.3, h: 0.35,
    fontFace: HEAD_FONT, fontSize: 11, bold: true, color: C.accent2, charSpacing: 6,
    align: 'center'
  });

  // Bottom quote
  s.addShape(pres.ShapeType.rect, {
    x: 0.4, y: 5.85, w: 12.5, h: 1.05,
    fill: { color: C.darkCard }, line: { color: C.darkCard }, shadow: mkShadow()
  });
  s.addShape(pres.ShapeType.rect, {
    x: 0.4, y: 5.85, w: 0.15, h: 1.05,
    fill: { color: C.accent2 }, line: { color: C.accent2 }
  });
  s.addText([
    { text: 'MVP 不需複雜 ML，', options: { color: 'FFFFFF' } },
    { text: '加權特徵即可展示', options: { color: C.accent2, bold: true } },
    { text: ' —— Agent 會從回饋持續學習。', options: { color: 'FFFFFF' } },
  ], {
    x: 0.7, y: 5.85, w: 12.1, h: 1.05,
    fontFace: HEAD_FONT, fontSize: 17, valign: 'middle', margin: 0
  });

  pageFooter(s, 10, TOTAL);
}

// ---------- Slide 11: MVP 範圍 ----------
{
  const s = pres.addSlide();
  s.background = { color: C.bg };
  pageHeader(s, 'SCOPE · MVP 務實取捨');
  pageTitle(s, '先證明核心價值，其他之後再說');

  // Two-column comparison
  // MVP column
  s.addShape(pres.ShapeType.rect, {
    x: 0.4, y: 2.0, w: 6.2, h: 4.5,
    fill: { color: C.darkCard }, line: { color: C.darkCard }, shadow: mkShadow()
  });
  s.addShape(pres.ShapeType.rect, {
    x: 0.4, y: 2.0, w: 6.2, h: 0.6,
    fill: { color: C.accent }, line: { color: C.accent }
  });
  s.addText('MVP · 現在做', {
    x: 0.4, y: 2.0, w: 6.2, h: 0.6,
    fontFace: HEAD_FONT, fontSize: 16, bold: true, color: 'FFFFFF',
    align: 'center', valign: 'middle', margin: 0, charSpacing: 4
  });

  // Future column
  s.addShape(pres.ShapeType.rect, {
    x: 7.1, y: 2.0, w: 5.8, h: 4.5,
    fill: { color: C.card }, line: { color: C.line, width: 1 }, shadow: mkShadow()
  });
  s.addShape(pres.ShapeType.rect, {
    x: 7.1, y: 2.0, w: 5.8, h: 0.6,
    fill: { color: C.accent2 }, line: { color: C.accent2 }
  });
  s.addText('FUTURE · 之後再做', {
    x: 7.1, y: 2.0, w: 5.8, h: 0.6,
    fontFace: HEAD_FONT, fontSize: 16, bold: true, color: C.ink,
    align: 'center', valign: 'middle', margin: 0, charSpacing: 4
  });

  const rows = [
    { k: 'Playlist 來源', mvp: '公開 Playlist URL', fut: 'Google OAuth / 私人 / 聆聽紀錄' },
    { k: 'YouTube Quota', mvp: '只在最後驗證步驟搜尋', fut: '快取 + 批次最佳化' },
    { k: '回饋學習',     mvp: '加權特徵向量',        fut: '線上學習模型' },
    { k: 'Audio 分析',   mvp: 'ReccoBeats',           fut: '自建分析 / 多來源融合' },
  ];

  rows.forEach((r, i) => {
    const y = 2.85 + i * 0.85;
    // Key label
    s.addText(r.k, {
      x: 0.65, y, w: 2.0, h: 0.4,
      fontFace: BODY_FONT, fontSize: 10, bold: true, color: C.accent2, charSpacing: 2
    });
    s.addText(r.mvp, {
      x: 0.65, y: y + 0.3, w: 5.7, h: 0.5,
      fontFace: HEAD_FONT, fontSize: 15, bold: true, color: 'FFFFFF', margin: 0
    });

    s.addText(r.k, {
      x: 7.35, y, w: 2.0, h: 0.4,
      fontFace: BODY_FONT, fontSize: 10, bold: true, color: C.muted, charSpacing: 2
    });
    s.addText(r.fut, {
      x: 7.35, y: y + 0.3, w: 5.3, h: 0.5,
      fontFace: HEAD_FONT, fontSize: 15, color: C.muted, margin: 0
    });

    // divider
    if (i < rows.length - 1) {
      s.addShape(pres.ShapeType.line, {
        x: 0.65, y: y + 0.78, w: 5.7, h: 0,
        line: { color: 'FFFFFF', transparency: 80, width: 0.5 }
      });
      s.addShape(pres.ShapeType.line, {
        x: 7.35, y: y + 0.78, w: 5.3, h: 0,
        line: { color: C.line, width: 0.5 }
      });
    }
  });

  // Bottom quote
  s.addShape(pres.ShapeType.rect, {
    x: 0.4, y: 6.65, w: 12.5, h: 0.6,
    fill: { color: C.accent2 }, line: { color: C.accent2 }
  });
  s.addText('先證明核心價值 — 不要第一版就卡在「為什麼 OAuth 又壞了」。', {
    x: 0.4, y: 6.65, w: 12.5, h: 0.6,
    fontFace: HEAD_FONT, fontSize: 15, bold: true, color: C.ink,
    align: 'center', valign: 'middle', italic: true, margin: 0
  });

  pageFooter(s, 11, TOTAL);
}

// ---------- Slide 12: Summary ----------
{
  const s = pres.addSlide();
  s.background = { color: C.ink };

  // Decorative dots top-right
  for (let r = 0; r < 5; r++) {
    for (let c = 0; c < 8; c++) {
      s.addShape(pres.ShapeType.ellipse, {
        x: 8.5 + c * 0.5, y: 0.5 + r * 0.5, w: 0.05, h: 0.05,
        fill: { color: C.accent, transparency: 50 },
        line: { color: C.accent, transparency: 50 }
      });
    }
  }

  s.addShape(pres.ShapeType.rect, {
    x: 0.7, y: 0.8, w: 0.9, h: 0.06,
    fill: { color: C.accent }, line: { color: C.accent }
  });
  s.addText('SUMMARY · 總結', {
    x: 0.7, y: 0.35, w: 6, h: 0.4,
    fontFace: BODY_FONT, fontSize: 12, bold: true, color: C.accent2, charSpacing: 6
  });

  s.addText([
    { text: 'Museek = ', options: { color: 'FFFFFF' } },
    { text: '理解需求 ', options: { color: C.accent2, bold: true } },
    { text: '× ', options: { color: 'FFFFFF' } },
    { text: '主動探索 ', options: { color: C.accent2, bold: true } },
    { text: '×\n', options: { color: 'FFFFFF' } },
    { text: '客觀分析 ', options: { color: C.accent2, bold: true } },
    { text: '× ', options: { color: 'FFFFFF' } },
    { text: '可解釋推薦', options: { color: C.accent2, bold: true } },
  ], {
    x: 0.7, y: 1.1, w: 12, h: 1.6,
    fontFace: HEAD_FONT, fontSize: 34, bold: true, margin: 0,
    paraSpaceAfter: 6
  });

  // 5 pillars
  const pillars = [
    { icon: '🎯', t: 'Discovery Distance', b: '重新定義「冷門」——\n有關聯但有驚喜' },
    { icon: '🎛️', t: '客觀 Audio Features', b: 'ReccoBeats 供資料，\n不靠 LLM 猜測' },
    { icon: '🧩', t: 'Retrieval / Research / Reasoning', b: '職責清楚的\n三元件設計' },
    { icon: '🛡️', t: '確定性驗證', b: '擋住 LLM 幻覺與\nprompt injection' },
    { icon: '🔁', t: '回饋迴圈', b: 'Agent 越用\n越懂你' },
  ];

  const pw = 2.4;
  const pgap = 0.15;
  const totalPW = pillars.length * pw + (pillars.length - 1) * pgap;
  const startX = (SW - totalPW) / 2;

  pillars.forEach((p, i) => {
    const x = startX + i * (pw + pgap);
    const y = 3.4;
    const h = 2.8;
    s.addShape(pres.ShapeType.rect, {
      x, y, w: pw, h,
      fill: { color: '2E1F4E' }, line: { color: C.accent2, width: 0.5 }
    });
    s.addShape(pres.ShapeType.rect, {
      x, y, w: pw, h: 0.08,
      fill: { color: C.accent }, line: { color: C.accent }
    });
    s.addText(p.icon, {
      x, y: y + 0.25, w: pw, h: 0.7,
      fontFace: HEAD_FONT, fontSize: 32, align: 'center', margin: 0
    });
    s.addText(p.t, {
      x: x + 0.15, y: y + 1.05, w: pw - 0.3, h: 0.85,
      fontFace: HEAD_FONT, fontSize: 13, bold: true, color: C.accent2,
      align: 'center', margin: 0
    });
    s.addText(p.b, {
      x: x + 0.15, y: y + 1.95, w: pw - 0.3, h: 0.75,
      fontFace: BODY_FONT, fontSize: 11, color: 'FFFFFF',
      align: 'center', margin: 0
    });
  });

  // Closing tagline
  s.addShape(pres.ShapeType.rect, {
    x: 0.7, y: 6.6, w: 0.06, h: 0.5,
    fill: { color: C.accent }, line: { color: C.accent }
  });
  s.addText('不只是推薦歌曲 —— 而是陪你探索音樂的夥伴。', {
    x: 0.9, y: 6.55, w: 11.5, h: 0.6,
    fontFace: HEAD_FONT, fontSize: 20, italic: true, color: 'FFFFFF', margin: 0
  });

  // Bottom-right marker
  s.addShape(pres.ShapeType.rect, {
    x: SW - 0.55, y: SH - 0.4, w: 0.12, h: 0.12,
    fill: { color: C.accent }, line: { color: C.accent }
  });
  s.addText('12 / 12', {
    x: SW - 1.6, y: SH - 0.45, w: 1.1, h: 0.3,
    fontFace: BODY_FONT, fontSize: 9, color: C.accent2, align: 'right'
  });
}

pres.writeFile({ fileName: 'Museek-Deck.pptx' })
  .then((f) => console.log(`✓ Wrote ${f}`))
  .catch((e) => { console.error(e); process.exit(1); });

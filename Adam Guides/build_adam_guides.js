// ============================================================
// A.D.A.M. — Axonify Data & Administration Manager
// How-To Guide Series — Document Builder
// Brand: Axonify Brand Book 2023
//
// SETUP:  npm install docx
// RUN:    node build_adam_guides.js
// OUTPUT: guides-output/ folder
// ============================================================

const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  Header, Footer, AlignmentType, LevelFormat,
  HeadingLevel, BorderStyle, WidthType, ShadingType,
  VerticalAlign, PageNumber, PageBreak
} = require('docx');
const fs   = require('fs');
const path = require('path');

const OUT = path.join(__dirname, 'guides-output');
if (!fs.existsSync(OUT)) fs.mkdirSync(OUT);

// ─── Axonify Brand Colours — Brand Book 2023 ─────────────────────────────
const B = {
  grass:       '00AA61',  // Primary green — CTAs, active states, H3
  forest:      '017551',  // Dark green — H2, table headers, cover band
  darkForest:  '02442E',  // Deepest dark panels
  almostBlack: '252D2A',  // All body text
  honeydew:    'DEFCE5',  // Step box backgrounds
  mint:        'DEF9EE',  // Note box backgrounds
  smoke:       'EFEFEF',  // Footer, alt table rows
  watercrest:  '029B55',  // Hyperlinks
  kumquat:     'F29A30',  // Warning accent
  tan:         'F9E7D4',  // Warning background
  lipstickRed: 'D8301A',  // Error / negative
  white:       'FFFFFF',
};

// ─── Border helpers ───────────────────────────────────────────────────────
const bdr    = (color = 'CCCCCC', size = 4) => ({ style: BorderStyle.SINGLE, size, color });
const noBdr  = () => ({ style: BorderStyle.NONE, size: 0, color: 'FFFFFF' });
const allBdr = (c, s = 4) => ({ top: bdr(c,s), bottom: bdr(c,s), left: bdr(c,s), right: bdr(c,s) });
const noBdrs = () => ({ top: noBdr(), bottom: noBdr(), left: noBdr(), right: noBdr() });

// ─── Spacing ──────────────────────────────────────────────────────────────
const sp = (before = 0, after = 100) => ({ before, after });

// ─── Primitives ───────────────────────────────────────────────────────────
const spacer = () =>
  new Paragraph({ spacing: sp(0,80), children: [new TextRun({ text: ' ', size: 18 })] });

const rule = () =>
  new Paragraph({
    spacing: sp(160, 160),
    border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: B.smoke, space: 1 } },
    children: [],
  });

const body = (text, bold = false) =>
  new Paragraph({
    spacing: sp(0, 100),
    children: [new TextRun({ text, size: 20, font: 'Calibri', color: B.almostBlack, bold })],
  });

const indented = (text) =>
  new Paragraph({
    spacing: sp(0, 80),
    indent: { left: 560 },
    children: [new TextRun({ text, size: 20, font: 'Calibri', color: B.almostBlack })],
  });

// ─── Headings ─────────────────────────────────────────────────────────────
const h1 = t => new Paragraph({ heading: HeadingLevel.HEADING_1, spacing: sp(400,120),
  children: [new TextRun({ text: t, font: 'Calibri', size: 40, bold: true, color: B.almostBlack })] });
const h2 = t => new Paragraph({ heading: HeadingLevel.HEADING_2, spacing: sp(280,80),
  children: [new TextRun({ text: t, font: 'Calibri', size: 28, bold: true, color: B.forest })] });
const h3 = t => new Paragraph({ heading: HeadingLevel.HEADING_3, spacing: sp(200,60),
  children: [new TextRun({ text: t, font: 'Calibri', size: 22, bold: true, color: B.grass })] });

// ─── Callout box ──────────────────────────────────────────────────────────
function callout(label, labelColor, bgColor, accentColor, lines, isCode = false) {
  const rows  = Array.isArray(lines) ? lines : [lines];
  const font  = isCode ? 'Courier New' : 'Calibri';
  const tc    = isCode ? B.honeydew    : B.almostBlack;
  return new Table({
    width: { size: 9360, type: WidthType.DXA },
    columnWidths: [160, 9200],
    borders: noBdrs(),
    rows: [new TableRow({ children: [
      new TableCell({
        width: { size: 160, type: WidthType.DXA }, borders: noBdrs(),
        shading: { fill: accentColor, type: ShadingType.CLEAR },
        margins: { top: 0, bottom: 0, left: 0, right: 0 },
        children: [new Paragraph({ children: [new TextRun({ text: ' ' })] })],
      }),
      new TableCell({
        width: { size: 9200, type: WidthType.DXA }, borders: noBdrs(),
        shading: { fill: bgColor, type: ShadingType.CLEAR },
        margins: { top: 120, bottom: 120, left: 200, right: 120 },
        children: [
          new Paragraph({ spacing: sp(0,60),
            children: [new TextRun({ text: label, bold: true, color: labelColor, size: 18, font: 'Calibri' })] }),
          ...rows.map(line => new Paragraph({ spacing: sp(0,40),
            children: [new TextRun({ text: line || ' ', size: isCode ? 18 : 20, font, color: tc })] })),
        ],
      }),
    ]})]
  });
}

// Callout shorthands
const noteBox    = l => callout('💡  Note',    B.forest,      B.mint,        B.grass,       l);
const warnBox    = l => callout('⚠️  Warning', B.kumquat,     B.tan,         B.kumquat,     l);
const successBox = l => callout('✅  Result',  B.grass,       B.honeydew,    B.grass,       l);
const errorBox   = l => callout('❌  Error',   B.lipstickRed, 'FFF5F5',      B.lipstickRed, l);
const soqlBox    = l => callout('SOQL',        B.honeydew,    B.almostBlack, B.grass,       l, true);
const adamBox    = l => callout('A.D.A.M.',    B.honeydew,    B.darkForest,  B.grass,       l, true);

// ─── Step box ─────────────────────────────────────────────────────────────
function stepBox(num, title, lines) {
  const rows = Array.isArray(lines) ? lines : [lines];
  return new Table({
    width: { size: 9360, type: WidthType.DXA },
    columnWidths: [420, 8940],
    borders: noBdrs(),
    rows: [new TableRow({ children: [
      new TableCell({
        width: { size: 420, type: WidthType.DXA }, borders: noBdrs(),
        shading: { fill: B.grass, type: ShadingType.CLEAR },
        margins: { top: 120, bottom: 120, left: 80, right: 80 },
        verticalAlign: VerticalAlign.TOP,
        children: [new Paragraph({ alignment: AlignmentType.CENTER,
          children: [new TextRun({ text: `${num}`, bold: true, color: B.white, size: 26, font: 'Calibri' })] })],
      }),
      new TableCell({
        width: { size: 8940, type: WidthType.DXA },
        borders: { top: noBdr(), bottom: noBdr(), right: noBdr(), left: bdr(B.honeydew, 8) },
        shading: { fill: B.honeydew, type: ShadingType.CLEAR },
        margins: { top: 100, bottom: 100, left: 200, right: 120 },
        children: [
          new Paragraph({ spacing: sp(0,60),
            children: [new TextRun({ text: title, bold: true, color: B.forest, size: 22, font: 'Calibri' })] }),
          ...rows.map(line => new Paragraph({ spacing: sp(0,40),
            children: [new TextRun({ text: line, size: 20, font: 'Calibri', color: B.almostBlack })] })),
        ],
      }),
    ]})]
  });
}

// ─── Screenshot placeholder ───────────────────────────────────────────────
function screenshot(caption) {
  return new Table({
    width: { size: 9360, type: WidthType.DXA }, columnWidths: [9360],
    rows: [new TableRow({ children: [new TableCell({
      width: { size: 9360, type: WidthType.DXA },
      borders: allBdr(B.forest, 6),
      shading: { fill: 'F2F8F5', type: ShadingType.CLEAR },
      margins: { top: 560, bottom: 560, left: 200, right: 200 },
      children: [
        new Paragraph({ alignment: AlignmentType.CENTER,
          children: [new TextRun({ text: '[ SCREENSHOT ]', bold: true, color: B.forest, size: 20, font: 'Calibri' })] }),
        new Paragraph({ alignment: AlignmentType.CENTER, spacing: sp(60,0),
          children: [new TextRun({ text: caption, color: '666666', size: 17, font: 'Calibri', italics: true })] }),
      ],
    })]})],
  });
}

// ─── Two-column info table ────────────────────────────────────────────────
function infoTable(rows) {
  return new Table({
    width: { size: 9360, type: WidthType.DXA }, columnWidths: [2800, 6560],
    rows: rows.map(([label, value], i) => new TableRow({ children: [
      new TableCell({ width: { size: 2800, type: WidthType.DXA }, borders: allBdr('CCCCCC',4),
        shading: { fill: i%2===0 ? B.honeydew : B.white, type: ShadingType.CLEAR },
        margins: { top:80, bottom:80, left:120, right:120 },
        children: [new Paragraph({ children: [new TextRun({ text: label, bold: true, size: 18, font: 'Calibri', color: B.forest })] })] }),
      new TableCell({ width: { size: 6560, type: WidthType.DXA }, borders: allBdr('CCCCCC',4),
        shading: { fill: i%2===0 ? B.honeydew : B.white, type: ShadingType.CLEAR },
        margins: { top:80, bottom:80, left:120, right:120 },
        children: [new Paragraph({ children: [new TextRun({ text: value, size: 18, font: 'Calibri', color: B.almostBlack })] })] }),
    ]})),
  });
}

// ─── Cover page ───────────────────────────────────────────────────────────
function coverPage(num, title, subtitle, version, date) {
  return [
    new Table({
      width: { size: 9360, type: WidthType.DXA }, columnWidths: [9360], borders: noBdrs(),
      rows: [new TableRow({ children: [new TableCell({
        width: { size: 9360, type: WidthType.DXA }, borders: noBdrs(),
        shading: { fill: B.forest, type: ShadingType.CLEAR },
        margins: { top: 300, bottom: 300, left: 400, right: 400 },
        children: [
          new Paragraph({ spacing: sp(0,60), children: [new TextRun({
            text: 'AXONIFY DATA & ADMINISTRATION MANAGER  ·  HOW-TO GUIDE',
            size: 16, bold: true, color: B.honeydew, font: 'Calibri', characterSpacing: 30 })] }),
          new Paragraph({ spacing: sp(0,0), children: [new TextRun({
            text: `Guide ${num} of 8  ·  A.D.A.M. Documentation Series`,
            size: 16, color: '75EABD', font: 'Calibri' })] }),
        ],
      })]})],
    }),
    spacer(), spacer(),
    new Paragraph({ spacing: sp(200,100),
      children: [new TextRun({ text: title, size: 72, bold: true, font: 'Calibri', color: B.almostBlack })] }),
    new Paragraph({ spacing: sp(0,160),
      border: { bottom: { style: BorderStyle.SINGLE, size: 20, color: B.grass, space: 1 } },
      children: [] }),
    new Paragraph({ spacing: sp(0,240),
      children: [new TextRun({ text: subtitle, size: 26, font: 'Calibri', color: B.forest })] }),
    new Table({
      width: { size: 9360, type: WidthType.DXA }, columnWidths: [2200, 7160], borders: noBdrs(),
      rows: [
        ['Version',      version],
        ['Last updated', date],
        ['Audience',     'RevOps / Sales Ops team'],
        ['Tool',         'A.D.A.M. — Axonify Data & Administration Manager'],
        ['Series',       'A.D.A.M. How-To Guides — 8 guides total'],
      ].map(([lbl, val]) => new TableRow({ children: [
        new TableCell({ width: { size: 2200, type: WidthType.DXA }, borders: noBdrs(),
          margins: { top:60, bottom:60, left:0, right:80 },
          children: [new Paragraph({ children: [new TextRun({ text: lbl, bold: true, size: 18, font: 'Calibri', color: B.forest })] })] }),
        new TableCell({ width: { size: 7160, type: WidthType.DXA }, borders: noBdrs(),
          margins: { top:60, bottom:60, left:80, right:0 },
          children: [new Paragraph({ children: [new TextRun({ text: val, size: 18, font: 'Calibri', color: B.almostBlack })] })] }),
      ]})),
    }),
    spacer(), spacer(), spacer(), spacer(), spacer(),
    new Table({
      width: { size: 9360, type: WidthType.DXA }, columnWidths: [9360], borders: noBdrs(),
      rows: [new TableRow({ children: [new TableCell({
        width: { size: 9360, type: WidthType.DXA },
        borders: { top: bdr(B.smoke, 4) },
        shading: { fill: B.smoke, type: ShadingType.CLEAR },
        margins: { top: 120, bottom: 120, left: 200, right: 200 },
        children: [new Paragraph({ children: [new TextRun({
          text: 'Axonify  ·  Salesforce Operations  ·  Internal use only  ·  Not for external distribution',
          size: 14, color: '888888', font: 'Calibri' })] })],
      })]})],
    }),
    new Paragraph({ children: [new PageBreak()] }),
  ];
}

// ─── Page header / footer ─────────────────────────────────────────────────
function pageHeader(num, title) {
  return [new Table({
    width: { size: 9360, type: WidthType.DXA }, columnWidths: [6800, 2560], borders: noBdrs(),
    rows: [new TableRow({ children: [
      new TableCell({ width: { size: 6800, type: WidthType.DXA },
        borders: { top: noBdr(), left: noBdr(), right: noBdr(), bottom: bdr(B.grass, 8) },
        margins: { top: 60, bottom: 60, left: 0, right: 0 },
        children: [new Paragraph({ children: [new TextRun({
          text: `A.D.A.M.  ·  Guide ${num}: ${title}`, size: 16, font: 'Calibri', color: B.forest })] })] }),
      new TableCell({ width: { size: 2560, type: WidthType.DXA },
        borders: { top: noBdr(), left: noBdr(), right: noBdr(), bottom: bdr(B.grass, 8) },
        margins: { top: 60, bottom: 60, left: 0, right: 0 },
        children: [new Paragraph({ alignment: AlignmentType.RIGHT, children: [
          new TextRun({ text: 'Page ', size: 16, font: 'Calibri', color: '888888' }),
          new TextRun({ children: [PageNumber.CURRENT], size: 16, font: 'Calibri', color: '888888' }),
          new TextRun({ text: ' of ', size: 16, font: 'Calibri', color: '888888' }),
          new TextRun({ children: [PageNumber.TOTAL_PAGES], size: 16, font: 'Calibri', color: '888888' }),
        ]})] }),
    ]})]
  })];
}

function pageFooter(num, title, version) {
  return [new Paragraph({
    border: { top: bdr(B.smoke, 4) }, spacing: sp(60, 0),
    children: [
      new TextRun({ text: `Axonify  ·  A.D.A.M.  ·  Guide ${num}: ${title}`, size: 14, font: 'Calibri', color: '888888' }),
      new TextRun({ text: `      ${version}  ·  Internal use only`, size: 14, font: 'Calibri', color: B.grass }),
    ],
  })];
}

// ─── Related guides table ─────────────────────────────────────────────────
const ALL_GUIDES = [
  { num: 1, title: 'Running Your First Query',            desc: 'AI, Visual, and Raw SOQL query modes' },
  { num: 2, title: 'Using the Cleanup Shortcuts Library', desc: 'Pre-built audit queries for common tasks' },
  { num: 3, title: 'Account Deduplication',               desc: 'Finding, reviewing, and merging duplicate Accounts' },
  { num: 4, title: 'Contact Deduplication',               desc: 'Deduplicating Contacts with scoring and safety caps' },
  { num: 5, title: 'Territory Map & Lookup',              desc: 'Viewing coverage and looking up states / provinces' },
  { num: 6, title: 'Territory Reassignment Wizard',       desc: 'Transferring Account ownership in 4 guided steps' },
  { num: 7, title: 'History & Audit Logs',                desc: 'Past queries, backup CSVs, and change logs' },
  { num: 8, title: 'Dry Run & Auto-Backup Safety',        desc: 'Previewing operations and recovering from backups' },
];

function relatedTable(nums) {
  const rows = ALL_GUIDES.filter(g => nums.includes(g.num));
  return new Table({
    width: { size: 9360, type: WidthType.DXA }, columnWidths: [480, 3200, 5680],
    rows: [
      new TableRow({ children: [
        new TableCell({ width:{size:480, type:WidthType.DXA}, borders:allBdr(B.forest,4), shading:{fill:B.forest,type:ShadingType.CLEAR}, margins:{top:80,bottom:80,left:120,right:120}, children:[new Paragraph({children:[new TextRun({text:'#',           bold:true,color:B.white,size:18,font:'Calibri'})]})] }),
        new TableCell({ width:{size:3200,type:WidthType.DXA}, borders:allBdr(B.forest,4), shading:{fill:B.forest,type:ShadingType.CLEAR}, margins:{top:80,bottom:80,left:120,right:120}, children:[new Paragraph({children:[new TextRun({text:'Guide',        bold:true,color:B.white,size:18,font:'Calibri'})]})] }),
        new TableCell({ width:{size:5680,type:WidthType.DXA}, borders:allBdr(B.forest,4), shading:{fill:B.forest,type:ShadingType.CLEAR}, margins:{top:80,bottom:80,left:120,right:120}, children:[new Paragraph({children:[new TextRun({text:'What it covers',bold:true,color:B.white,size:18,font:'Calibri'})]})] }),
      ]}),
      ...rows.map((g,i) => new TableRow({ children: [
        new TableCell({ width:{size:480, type:WidthType.DXA}, borders:allBdr('CCCCCC',4), shading:{fill:i%2===0?B.white:B.honeydew,type:ShadingType.CLEAR}, margins:{top:80,bottom:80,left:120,right:120}, children:[new Paragraph({children:[new TextRun({text:`${g.num}`,bold:true,size:18,font:'Calibri',color:B.grass})]})] }),
        new TableCell({ width:{size:3200,type:WidthType.DXA}, borders:allBdr('CCCCCC',4), shading:{fill:i%2===0?B.white:B.honeydew,type:ShadingType.CLEAR}, margins:{top:80,bottom:80,left:120,right:120}, children:[new Paragraph({children:[new TextRun({text:g.title,bold:true,size:18,font:'Calibri',color:B.forest})]})] }),
        new TableCell({ width:{size:5680,type:WidthType.DXA}, borders:allBdr('CCCCCC',4), shading:{fill:i%2===0?B.white:B.honeydew,type:ShadingType.CLEAR}, margins:{top:80,bottom:80,left:120,right:120}, children:[new Paragraph({children:[new TextRun({text:g.desc, size:18,font:'Calibri',color:B.almostBlack})]})] }),
      ]})),
    ],
  });
}

// ─── Standard doc wrapper ─────────────────────────────────────────────────
function makeDoc(num, title, version, children) {
  return new Document({
    styles: {
      default: { document: { run: { font: 'Calibri', size: 20, color: B.almostBlack } } },
      paragraphStyles: [
        { id:'Heading1',name:'Heading 1',basedOn:'Normal',next:'Normal',quickFormat:true, run:{size:40,bold:true,font:'Calibri',color:B.almostBlack}, paragraph:{spacing:{before:400,after:120},outlineLevel:0} },
        { id:'Heading2',name:'Heading 2',basedOn:'Normal',next:'Normal',quickFormat:true, run:{size:28,bold:true,font:'Calibri',color:B.forest},      paragraph:{spacing:{before:280,after:80}, outlineLevel:1} },
        { id:'Heading3',name:'Heading 3',basedOn:'Normal',next:'Normal',quickFormat:true, run:{size:22,bold:true,font:'Calibri',color:B.grass},       paragraph:{spacing:{before:200,after:60}, outlineLevel:2} },
      ],
    },
    numbering: { config: [
      { reference:'bullets', levels:[{ level:0, format:LevelFormat.BULLET,  text:'•',  alignment:AlignmentType.LEFT, style:{ paragraph:{indent:{left:720,hanging:360}}, run:{color:B.grass} } }] },
      { reference:'numbers', levels:[{ level:0, format:LevelFormat.DECIMAL, text:'%1.',alignment:AlignmentType.LEFT, style:{ paragraph:{indent:{left:720,hanging:360}} } }] },
    ]},
    sections: [{
      properties: { page: { size:{width:12240,height:15840}, margin:{top:1080,right:1080,bottom:1080,left:1080} } },
      headers: { default: new Header({ children: pageHeader(num, title) }) },
      footers: { default: new Footer({ children: pageFooter(num, title, version) }) },
      children,
    }],
  });
}

async function save(doc, filename) {
  const out = path.join(OUT, filename);
  fs.writeFileSync(out, await Packer.toBuffer(doc));
  console.log(`  ✓  ${filename}`);
  return out;
}

// ══════════════════════════════════════════════════════════════════════════
// SETUP GUIDE
// ══════════════════════════════════════════════════════════════════════════
async function buildSetupGuide() {
  const children = [
    ...coverPage('0', 'Setup & Access Guide', 'How to access A.D.A.M. via the shared web interface, or install and run it on your own machine', 'v1.0', 'March 2026'),

    h1('1. What is A.D.A.M.?'),
    body('A.D.A.M. stands for Axonify Data & Administration Manager. It is an internal Salesforce operations tool built for the RevOps and Sales Ops team. It connects directly to our Salesforce production org and lets you run queries, clean up data, manage territories, and deduplicate records — without needing to write code or use Data Loader.'),
    spacer(),
    noteBox('A.D.A.M. can both read and write to Salesforce. Queries are always safe and read-only. Any operation that modifies Salesforce data requires reviewing a Dry Run first, and automatically creates backup CSV files before making any changes.'),
    spacer(),
    h2('What A.D.A.M. can do'),
    infoTable([
      ['Query Builder',             'Run SOQL queries using AI plain-English input, Visual Builder dropdowns, or Raw SOQL. Export results to CSV.'],
      ['Cleanup Shortcuts',         'One-click access to pre-built audit queries for common Salesforce cleanup tasks.'],
      ['Account Deduplication',     'Find and merge duplicate Account records with match scoring and manual review.'],
      ['Contact Deduplication',     'Find and merge duplicate Contact records with safety caps and match transparency.'],
      ['Territory Map & Lookup',    'View territory coverage and look up which territory any state or province belongs to.'],
      ['Territory Reassignment',    'Transfer Account (and optionally Contact and Opportunity) ownership between reps in a guided 4-step wizard.'],
      ['History & Audit Logs',      'Review past queries, see what data was changed, and access backup CSVs from previous operations.'],
      ['Dry Run & Auto-Backup',     'Preview any write operation before committing. Automatic CSV backups run before every live execution.'],
    ]),
    spacer(),
    rule(),

    h1('2. Option A — Shared Web Interface (Recommended)'),
    body('The easiest way to use A.D.A.M. No installation required. Works in any modern web browser.'),
    spacer(),
    stepBox(1, 'Get the URL from your Salesforce admin', [
      'A.D.A.M. runs as a shared web application. Ask your Salesforce admin for the current URL.',
      'It will look something like:  https://axonify-adam.streamlit.app',
    ]),
    spacer(),
    stepBox(2, 'Open the URL in Chrome or Firefox', ['A.D.A.M. works best in Chrome. Avoid Safari or Internet Explorer.']),
    spacer(),
    stepBox(3, 'Log in with your Axonify Okta account', [
      'Click "Connect to Salesforce".',
      'You will be redirected to the Axonify Okta login page.',
      'Use your normal Axonify work email and password.',
      'You will only need to do this once per browser session.',
    ]),
    spacer(),
    stepBox(4, 'Start using A.D.A.M.', ['The left sidebar shows all available modules. Start with Guide 1 — Running Your First Query to get familiar with the tool.']),
    spacer(),
    screenshot('A.D.A.M. web interface — left sidebar showing all 8 modules, green "Connected to Salesforce" status indicator at the bottom'),
    spacer(),
    warnBox([
      'Do not share the A.D.A.M. URL externally. It provides direct access to Salesforce production data.',
      'If you think the URL has been shared with someone who should not have access, contact your Salesforce admin immediately.',
    ]),
    spacer(),
    rule(),

    h1('3. Option B — Run on Your Own Machine'),
    body('Use this option if the shared web interface is unavailable, or if your admin has asked you to run A.D.A.M. locally. This requires a one-time setup that takes about 10 minutes.'),
    spacer(),

    h2('Step 1 — Check if Python is installed'),
    body('Open a terminal on your computer:'),
    indented('Mac:     Press Cmd + Space, type Terminal, press Enter'),
    indented('Windows: Press the Windows key, type cmd, press Enter'),
    spacer(),
    body('Type the following and press Enter:'),
    soqlBox(['python --version']),
    body('If you see a version number like "Python 3.10.0" — Python is installed. Skip to Step 2.'),
    body('If you see an error, go to https://python.org, click Downloads, and install the latest version. Tick "Add Python to PATH" during installation, then reopen your terminal.'),
    spacer(),

    h2('Step 2 — Get the A.D.A.M. project files'),
    stepBox(1, 'Download the project files', ['Your Salesforce admin will provide a ZIP file or a link to download A.D.A.M. Save the folder somewhere easy to find — for example, Documents/adam-tool']),
    spacer(),
    stepBox(2, 'Open your terminal in that folder', [
      'Mac:     Right-click the adam-tool folder in Finder and select "New Terminal at Folder"',
      'Windows: Open the folder in File Explorer, click the address bar at the top, type cmd, and press Enter',
    ]),
    spacer(),

    h2('Step 3 — Install dependencies'),
    body('In your terminal, type the following exactly and press Enter:'),
    soqlBox(['pip install streamlit simple-salesforce pandas --break-system-packages']),
    body('You will see a lot of text scroll by as packages download. This is normal. Wait for the blinking cursor to return before continuing. This step only needs to be done once.'),
    spacer(),
    noteBox('If you see a "pip: command not found" error, try using "pip3" instead of "pip" in the command above.'),
    spacer(),

    h2('Step 4 — Start A.D.A.M.'),
    body('In your terminal, type the following and press Enter:'),
    soqlBox(['streamlit run adam_tool.py']),
    body('Your browser will open automatically at http://localhost:8501 — this is A.D.A.M. running on your local machine.'),
    spacer(),
    stepBox(1, 'Log in with Salesforce SSO', ['Click "Connect to Salesforce". Log in with your Axonify Okta email and password. A.D.A.M. will remember your connection for the rest of the session.']),
    spacer(),
    screenshot('Browser at localhost:8501 — A.D.A.M. login screen, "Connect to Salesforce" button, Okta login prompt'),
    spacer(),
    warnBox([
      'Do not close the terminal window while using A.D.A.M. — it is what keeps the app running.',
      'To stop A.D.A.M. when you are done, click inside the terminal window and press Ctrl + C.',
    ]),
    spacer(),
    rule(),

    h1('4. Troubleshooting'),
    errorBox(['"pip: command not found" or "python: command not found"',
      'Python was not added to your system PATH during installation. Re-run the Python installer, and make sure the "Add Python to PATH" checkbox is ticked. Then reopen your terminal and try again.']),
    spacer(),
    errorBox(['"Module not found" error when starting A.D.A.M.',
      'The pip install step in Step 3 did not complete successfully. Run it again. If it fails a second time, contact your Salesforce admin.']),
    spacer(),
    errorBox(['"Connection refused" or the browser does not open automatically',
      'Manually type http://localhost:8501 into your browser address bar. If the page still does not load, check that your terminal is still showing the Streamlit running message and has not stopped.']),
    spacer(),
    errorBox(['"Authentication failed" during Salesforce login',
      'Make sure you are using your Axonify work email — not a personal email. If your Okta password has recently expired, reset it at okta.axonify.com before trying again.']),
    spacer(),
    rule(),

    h1('5. Getting Help'),
    body('For questions about A.D.A.M. or Salesforce data: contact your Salesforce Administrator.'),
    body('For Salesforce login or Okta issues: contact the IT Help Desk or reset your password at okta.axonify.com.'),
    body('For setup issues on your local machine: your Salesforce admin can walk you through the steps on a quick call.'),
    spacer(),
    rule(),

    h1('6. Guide Index — All 8 Guides'),
    relatedTable([1,2,3,4,5,6,7,8]),
  ];

  const doc = makeDoc('0', 'Setup & Access Guide', 'v1.0', children);
  return save(doc, '00-setup-and-access-guide.docx');
}

// ══════════════════════════════════════════════════════════════════════════
// MASTER TEMPLATE
// ══════════════════════════════════════════════════════════════════════════
async function buildMasterTemplate() {
  const children = [
    ...coverPage('X', 'Guide Title Here', 'One-sentence description of what this guide covers', 'v1.0', 'Month Year'),

    h1('1. Overview'),
    body('Explain what the feature does, when to use it, and what it affects in Salesforce. Write for a RevOps or Sales Ops audience — not a developer. Aim for 2–3 short paragraphs.'),
    spacer(),
    noteBox('This is a Note box. Use it for helpful tips, background context, or things users should know before starting.'),
    spacer(),
    warnBox('This is a Warning box. Use it for important cautions immediately before a step or action.'),
    spacer(),
    successBox(['This is a Result / Success box. Use it to show what a completed operation looks like.', 'Example:  Accounts updated: 18 / 18   |   Contacts updated: 44 / 44']),
    spacer(),
    errorBox('This is an Error box. Use it in Troubleshooting to describe a specific error message.'),
    spacer(),
    soqlBox(['SELECT Id, Name FROM Account WHERE BillingState = \'CA\' LIMIT 100']),
    spacer(),
    adamBox(['A.D.A.M. output block — use for showing simulated dry run results or tool output.']),
    spacer(),
    rule(),

    h1('2. Before You Start'),
    body('List prerequisites. Common ones:'),
    indented('A.D.A.M. is running — via the shared web URL or locally (see Setup Guide)'),
    indented('You are authenticated — the tool will prompt for Okta login if not already connected'),
    indented('Dry Run Mode is ON in the left sidebar for any operation that modifies data'),
    indented('Any prerequisite steps from other guides are complete (note which guide here)'),
    spacer(),
    rule(),

    h1('3. Step-by-Step Guide'),
    h2('Phase heading — Forest Green. Use for major phases within a guide.'),
    h3('Sub-heading — Grass Green. Use for named scenarios or distinct sub-steps.'),
    spacer(),
    stepBox(1, 'Step title — short and action-oriented', [
      'Describe exactly what the user clicks or types.',
      'Add a second line if the step needs more explanation.',
    ]),
    spacer(),
    stepBox(2, 'Second step', ['One line is fine for simple steps.']),
    spacer(),
    screenshot('Describe what this screenshot should show'),
    spacer(),
    rule(),

    h1('4. Worked Example'),
    body('Walk through a realistic Axonify scenario end-to-end. Use real territory names, realistic record counts, and familiar rep names. Show the SOQL generated, the result count, and the outcome.'),
    spacer(),
    rule(),

    h1('5. Troubleshooting'),
    body('Cover the 3–5 most common issues. Use the Error box for specific error messages and the Warning box for general cautions.'),
    spacer(),
    rule(),

    h1('6. Related Guides'),
    relatedTable([1,2,3,4,5,6,7,8]),
  ];
  const doc = makeDoc('X', 'Master Template', 'v1.0', children);
  return save(doc, '00-MASTER-TEMPLATE.docx');
}

// ══════════════════════════════════════════════════════════════════════════
// GUIDE 1 — Running Your First Query
// ══════════════════════════════════════════════════════════════════════════
async function buildGuide1() {
  const children = [
    ...coverPage(1, 'Running Your First Query', 'Use AI, Visual Builder, or Raw SOQL mode to extract data from your Salesforce org', 'v1.0', 'March 2026'),

    h1('1. Overview'),
    body('A.D.A.M. gives you three ways to query Salesforce. You do not need to know SOQL to get started — AI mode writes the query for you based on a plain-English description.'),
    spacer(),
    infoTable([
      ['AI Mode',       'Describe what you want in plain English. A.D.A.M. generates the SOQL for you. Recommended for most users.'],
      ['Visual Builder','Select object, fields, and filters from dropdown menus. No typing required.'],
      ['Raw SOQL',      'Type or paste a query directly. Best for pre-written queries or experienced Salesforce admins.'],
    ]),
    spacer(),
    noteBox('All three modes produce the same result: a SOQL query that runs against your live Salesforce org. The difference is only in how you build it.'),
    spacer(),
    warnBox('SELECT queries are always read-only and safe to run at any time. Dry Run Mode only needs to be ON when running operations that write data back to Salesforce.'),
    spacer(),
    rule(),

    h1('2. Before You Start'),
    body('A.D.A.M. must be running. See the Setup Guide (Guide 0) if you need access.'),
    indented('Shared web interface (recommended): open the URL your admin provided in Chrome'),
    indented('Local: run "streamlit run adam_tool.py" in your terminal from the A.D.A.M. folder'),
    body('You must be authenticated. A.D.A.M. will prompt for your Axonify Okta login if not already connected.'),
    body('You need at least Read access in Salesforce to the objects you want to query.'),
    spacer(),
    rule(),

    h1('3. Step-by-Step Guide'),
    h2('Using AI Mode (Recommended)'),
    stepBox(1, 'Open the Query Builder', ['Click "Query Builder" in the left sidebar of A.D.A.M.']),
    spacer(),
    stepBox(2, 'Select AI mode', ['Click the AI tab at the top of the Query Builder. It will highlight in green when active.']),
    spacer(),
    screenshot('A.D.A.M. Query Builder — AI tab selected (green highlight), plain-English input field below'),
    spacer(),
    stepBox(3, 'Describe your query', [
      'Type what you need in the input box. Be specific about the object, any filters, and what fields you want back.',
      '    Good:      "All Accounts in Territory 2 with no Opportunity in the last 6 months"',
      '    Too vague: "Show me accounts"',
    ]),
    spacer(),
    stepBox(4, 'Click Generate', [
      'A.D.A.M. writes the SOQL and shows it in the preview box.',
      'Review it before running — you can edit the generated SOQL directly if needed.',
    ]),
    spacer(),
    stepBox(5, 'Click Run Query', ['Results appear in the Results panel on the right. The row count is shown at the top.']),
    spacer(),
    stepBox(6, 'Export to CSV (optional)', ['Click the Export button. Files save automatically to the sf_exports/ folder, named with the object and today\'s date.']),
    spacer(),
    screenshot('Results panel — row count at top, table of results, Export button top-right corner'),
    spacer(),

    h2('Using Visual Builder Mode'),
    stepBox(1, 'Select your Object', ['Use the Object dropdown. Common options: Account, Contact, Opportunity, Lead, Task.']),
    spacer(),
    stepBox(2, 'Choose your Fields', ['Tick the fields you want returned. Common fields are pre-selected. Use the search box to find a specific field by name.']),
    spacer(),
    stepBox(3, 'Add Filters', ['Click "Add Filter". Set the field, operator (equals / contains / greater than / etc.), and value. Stack multiple filters as needed.']),
    spacer(),
    stepBox(4, 'Set a Row Limit', ['Default is 500 rows. Maximum is 2,000. Always add a date filter when querying high-volume objects like Task or Event.']),
    spacer(),
    stepBox(5, 'Click Run', ['Results load in the panel. The SOQL that A.D.A.M. generated is shown below the results for reference or copying.']),
    spacer(),
    screenshot('Visual Builder — Object dropdown showing "Account", two fields checked, one filter row visible'),
    spacer(),
    rule(),

    h1('4. Worked Example'),
    h2('Finding stale accounts in Territory 2'),
    body('The RevOps team wants a list of West Coast accounts (Territory 2) with no Opportunity activity in the last 6 months, to flag for the sales team for follow-up.'),
    spacer(),
    h3('Input typed into AI Mode'),
    body('"Show all Accounts in Territory 2 (BillingState in CA, OR, WA, BC, AB) owned by active Salesforce users, where the most recent Opportunity CloseDate was more than 180 days ago, or where no Opportunities exist at all. Return Account Name, Owner Name, BillingState, and most recent Opportunity CloseDate."'),
    spacer(),
    h3('A.D.A.M. generated this SOQL'),
    soqlBox([
      'SELECT Id, Name, Owner.Name, BillingState,',
      '       (SELECT MAX(CloseDate) FROM Opportunities)',
      'FROM Account',
      'WHERE BillingState IN (\'CA\',\'OR\',\'WA\',\'BC\',\'AB\')',
      '  AND Owner.IsActive = true',
      'ORDER BY Name ASC',
      'LIMIT 500',
    ]),
    spacer(),
    body('Result: 47 accounts returned. Exported to sf_exports/account_territory2_stale_2026-03-03.csv and shared with the sales manager for review and follow-up.'),
    spacer(),
    screenshot('Results panel — 47 rows returned. Columns: Account Name, Owner, BillingState, Last CloseDate. Export button visible.'),
    spacer(),
    rule(),

    h1('5. Troubleshooting'),
    errorBox(['"Query returned 0 results"',
      'Your filters may be too restrictive. Remove filters one at a time to find which one is excluding all records. Also confirm you selected the correct Salesforce object.']),
    spacer(),
    errorBox(['"INVALID_FIELD" error',
      'A field name in the query does not exist on that object. In Salesforce Setup, find the field and check its API Name — it is case-sensitive and may differ from the label shown in the Salesforce UI.']),
    spacer(),
    errorBox(['"Query too complex" or governor limit error',
      'Reduce the row LIMIT, remove sub-queries, or split into two smaller queries. Always add a date filter when querying Task, Event, or other high-volume objects.']),
    spacer(),
    warnBox('A.D.A.M. runs against your live Salesforce production org. Query results reflect real data. Do not share CSV exports outside the team without checking for personally identifiable information first.'),
    spacer(),
    rule(),

    h1('6. Related Guides'),
    relatedTable([2, 7, 8]),
  ];
  return save(makeDoc(1, 'Running Your First Query', 'v1.0', children), 'guide-01-running-your-first-query.docx');
}

// ══════════════════════════════════════════════════════════════════════════
// GUIDE 6 — Territory Reassignment Wizard
// ══════════════════════════════════════════════════════════════════════════
async function buildGuide6() {
  const children = [
    ...coverPage(6, 'Territory Reassignment Wizard', 'Transfer Account ownership between sales reps in 4 guided steps, with optional migration of Contacts and open Opportunities', 'v1.0', 'March 2026'),

    h1('1. Overview'),
    body('The Territory Reassignment Wizard transfers Account ownership from one sales rep to another within a defined territory. It handles Accounts, Contacts, and open Opportunities in one safe, fully auditable operation — with automatic backups created before any data changes.'),
    spacer(),
    noteBox('Use this wizard when a rep leaves the team, a territory is being reassigned, or accounts need redistributing between reps. It replaces doing this manually in Salesforce or through Data Loader.'),
    spacer(),
    h2('What gets migrated'),
    new Table({
      width: { size: 9360, type: WidthType.DXA }, columnWidths: [2800, 2200, 4360],
      rows: [
        new TableRow({ children: [
          new TableCell({ width:{size:2800,type:WidthType.DXA}, borders:allBdr(B.forest,4), shading:{fill:B.forest,type:ShadingType.CLEAR}, margins:{top:80,bottom:80,left:120,right:120}, children:[new Paragraph({children:[new TextRun({text:'Object',           bold:true,color:B.white,size:18,font:'Calibri'})]})] }),
          new TableCell({ width:{size:2200,type:WidthType.DXA}, borders:allBdr(B.forest,4), shading:{fill:B.forest,type:ShadingType.CLEAR}, margins:{top:80,bottom:80,left:120,right:120}, children:[new Paragraph({children:[new TextRun({text:'Default',          bold:true,color:B.white,size:18,font:'Calibri'})]})] }),
          new TableCell({ width:{size:4360,type:WidthType.DXA}, borders:allBdr(B.forest,4), shading:{fill:B.forest,type:ShadingType.CLEAR}, margins:{top:80,bottom:80,left:120,right:120}, children:[new Paragraph({children:[new TextRun({text:'Notes',            bold:true,color:B.white,size:18,font:'Calibri'})]})] }),
        ]}),
        ...[
          ['Account (OwnerId)',     'Always — cannot disable', 'The core action. Every included Account is reassigned.'],
          ['Contact (OwnerId)',     'ON — toggle off in Step 3','All Contacts at included Accounts. Turn off to leave with original rep.'],
          ['Opportunity (OwnerId)','ON — toggle off in Step 3','Open deals only. Closed Won / Closed Lost are never touched, ever.'],
          ['Activity history',     'Never migrated',           'Tasks, Events, and Email history always stay with original owner.'],
          ['Territory__c field',   'Never modified',           'Geographic territory field is separate from rep ownership.'],
        ].map(([o,d,n],i) => new TableRow({ children: [
          new TableCell({ width:{size:2800,type:WidthType.DXA}, borders:allBdr('CCCCCC',4), shading:{fill:i%2===0?B.white:B.honeydew,type:ShadingType.CLEAR}, margins:{top:80,bottom:80,left:120,right:120}, children:[new Paragraph({children:[new TextRun({text:o,bold:true,size:18,font:'Calibri',color:B.almostBlack})]})] }),
          new TableCell({ width:{size:2200,type:WidthType.DXA}, borders:allBdr('CCCCCC',4), shading:{fill:i%2===0?B.white:B.honeydew,type:ShadingType.CLEAR}, margins:{top:80,bottom:80,left:120,right:120}, children:[new Paragraph({children:[new TextRun({text:d,  size:18,font:'Calibri',color:B.forest})]})] }),
          new TableCell({ width:{size:4360,type:WidthType.DXA}, borders:allBdr('CCCCCC',4), shading:{fill:i%2===0?B.white:B.honeydew,type:ShadingType.CLEAR}, margins:{top:80,bottom:80,left:120,right:120}, children:[new Paragraph({children:[new TextRun({text:n,  size:18,font:'Calibri',color:B.almostBlack})]})] }),
        ]})),
      ],
    }),
    spacer(),
    warnBox(['Run Account Deduplication (Guide 3) before using this wizard.', 'Reassigning accounts that are later merged can create ownership inconsistencies that are difficult to untangle.']),
    spacer(),
    rule(),

    h1('2. Before You Start'),
    body('Know the territory and both rep names before opening the wizard.'),
    indented('Outgoing rep: the person currently owning the accounts'),
    indented('Incoming rep: the person who will take over ownership'),
    body('Note any accounts that should NOT be transferred — you will deselect them individually in Step 2.'),
    body('Turn on Dry Run Mode in the A.D.A.M. left sidebar. Always preview before executing live.'),
    spacer(),
    rule(),

    h1('3. Step-by-Step Guide'),
    h2('Opening the Wizard'),
    stepBox(1, 'Go to Territory Management', ['Click "Territory Mgmt" in the left sidebar of A.D.A.M.']),
    spacer(),
    stepBox(2, 'Open the Reassign tab', ['Click the Reassign sub-tab at the top of the Territory Management panel. Step 1 of the wizard loads automatically.']),
    spacer(),
    screenshot('A.D.A.M. Territory Mgmt panel — Reassign sub-tab selected, Step 1 form visible with territory and rep dropdowns'),
    spacer(),

    h2('Step 1 — Select Territory & Reps'),
    stepBox(1, 'Select the territory', ['Choose from: Territory 1 (East Coast US), Territory 2 (West Coast US + Canada), Territory 3 (Central US), Territory 4 (Southern US), or Europe 1.']),
    spacer(),
    stepBox(2, 'Select the Outgoing Rep', ['The rep currently owning the accounts. Only shows active Salesforce users who own accounts in the selected territory. If a rep is missing, they own no accounts there.']),
    spacer(),
    stepBox(3, 'Select the Incoming Rep', ['The rep taking ownership. The outgoing rep is automatically excluded from this dropdown — A.D.A.M. prevents selecting the same person for both roles.']),
    spacer(),
    stepBox(4, 'Click Next', ['A.D.A.M. queries Salesforce for all matching accounts. This may take a moment for large territories.']),
    spacer(),
    screenshot('Step 1 complete — Territory 2 selected, Outgoing Rep: Alex Chen, Incoming Rep: Jamie Park, Next button active'),
    spacer(),

    h2('Step 2 — Preview Affected Records'),
    body('Every Account that will be affected is listed here, with Contact and Opportunity counts per row. Review this carefully — this is your chance to exclude anything before any data changes.'),
    spacer(),
    stepBox(1, 'Review the full account list', ['Each row shows: Account name, billing state, account type, Contact count, and open Opportunity count.']),
    spacer(),
    stepBox(2, 'Deselect any accounts to keep with the current owner', ['Uncheck the Include checkbox on any Account you do not want to reassign. That row\'s Contacts and open Opportunities are automatically excluded too.']),
    spacer(),
    noteBox(['The summary bar at the bottom updates live as you check and uncheck rows:', '"17 accounts selected  ·  44 contacts  ·  9 open opportunities  ·  1 excluded"']),
    spacer(),
    stepBox(3, 'Click Next: Set Scope', ['At least 1 account must remain selected to proceed.']),
    spacer(),
    screenshot('Step 2 — account table with Include checkboxes. One row (Initech Ltd) unchecked showing EXCLUDED badge. Summary bar at bottom.'),
    spacer(),

    h2('Step 3 — Set Migration Scope'),
    body('Choose whether Contacts and open Opportunities migrate alongside the Accounts.'),
    spacer(),
    stepBox(1, 'Review the three scope rows', [
      'Account Ownership — always on. Cannot be disabled. This is the core purpose of the wizard.',
      'Contact Ownership — toggle ON/OFF. Default ON. Turn off to leave Contacts with the original rep.',
      'Open Opportunity Ownership — toggle ON/OFF. Default ON. Turn off to leave open deals with original rep.',
    ]),
    spacer(),
    stepBox(2, 'Adjust toggles if needed', ['Turning either toggle off is uncommon, but useful in partial handover situations where the incoming rep should not yet own all associated records.']),
    spacer(),
    warnBox('Closed Won and Closed Lost Opportunities are never reassigned — this is hardcoded, not a toggle. Historical revenue records are always protected regardless of any settings.'),
    spacer(),
    stepBox(3, 'Click Next: Confirm', ['Proceed to the final review screen.']),
    spacer(),
    screenshot('Step 3 — Scope panel: Account row (locked with shield icon), Contact toggle ON green, Opportunity toggle ON green'),
    spacer(),

    h2('Step 4 — Confirm & Execute'),
    body('The final review before anything changes in Salesforce. Read through the summary table carefully. The Execute button will not activate until you check the confirmation box.'),
    spacer(),
    stepBox(1, 'Review the summary table', ['Verify the Object, record count, field being updated, and action for each row. Check the From and To rep names displayed below the table.']),
    spacer(),
    stepBox(2, 'Run a Dry Run first (strongly recommended)', [
      'With Dry Run Mode ON in the sidebar, click "Preview (Dry Run)".',
      'A.D.A.M. simulates the full operation and shows expected record counts without writing anything.',
      'Confirm the numbers match your expectation before switching to live execution.',
    ]),
    spacer(),
    noteBox('A dry run takes under 10 seconds. Always do one before executing live — it costs nothing and confirms everything looks right.'),
    spacer(),
    stepBox(3, 'Check the confirmation checkbox', ['"I have reviewed the summary and want to proceed." The Execute button stays greyed out until this is checked.']),
    spacer(),
    stepBox(4, 'Click Execute Reassignment', [
      'A.D.A.M. runs the operation in this fixed order:',
      '  1.  Backup Accounts to CSV  then  update Account OwnerId',
      '  2.  Backup Contacts to CSV  then  update Contact OwnerId',
      '  3.  Backup Opportunities to CSV  then  update Opportunity OwnerId',
      'If the Account step fails, Contacts and Opportunities are not attempted.',
    ]),
    spacer(),
    screenshot('Step 4 — Summary table: 17 Accounts / 44 Contacts / 9 Opportunities. Confirmation checkbox checked. Execute button active.'),
    spacer(),
    rule(),

    h1('4. Worked Example'),
    h2('Alex Chen moves to management — Territory 2 transfers to Jamie Park'),
    body('Alex Chen is moving into a management role and her 18 Territory 2 accounts need to transfer to Jamie Park, who is taking over the West Coast patch. One account — Initech Ltd — is in active contract negotiation handled directly by the VP of Sales and should stay with Alex for now.'),
    spacer(),
    h3('Setup'),
    infoTable([
      ['Territory',      'Territory 2 — West Coast US + Canada (CA, OR, WA, BC, AB)'],
      ['Outgoing rep',   'Alex Chen'],
      ['Incoming rep',   'Jamie Park'],
      ['Total accounts', '18 accounts owned by Alex Chen in Territory 2'],
      ['Excluded',       'Initech Ltd — manually deselected in Step 2'],
    ]),
    spacer(),
    h3('Dry Run result — Step 4'),
    adamBox([
      'DRY RUN  —  no data written to Salesforce',
      '',
      'Territory:             Territory 2',
      'From:                  Alex Chen',
      'To:                    Jamie Park',
      '',
      'Accounts to update:      17 / 17',
      'Contacts to update:      44 / 44',
      'Opportunities to update:  9 / 9   (open only)',
      '',
      'Excluded by user:         1   (Initech Ltd)',
      'Closed opps protected:    3   (never updated)',
    ]),
    spacer(),
    body('Dry run confirmed. Confirmation box checked. Execute clicked.'),
    spacer(),
    h3('Live execution result'),
    successBox([
      'Execution complete',
      '',
      'Accounts updated:        17 / 17',
      'Contacts updated:        44 / 44',
      'Opportunities updated:    9 / 9',
      '',
      'Backup files saved to:   sf_backups/reassign_territory2_alex-to-jamie_2026-03-03/',
    ]),
    spacer(),
    screenshot('Post-execution result panel — green success row counts for all three objects, backup folder path shown'),
    spacer(),
    rule(),

    h1('5. Troubleshooting'),
    errorBox(['"No accounts found for this rep in this territory"',
      'The selected rep owns no Accounts with a BillingState matching the territory. Check: (1) Is the correct rep selected? (2) Do their Accounts have BillingState populated? Use Guide 1 to run: SELECT Id, Name, BillingState FROM Account WHERE OwnerId = \'[rep ID]\' to verify.']),
    spacer(),
    errorBox(['"Execute button is greyed out"',
      'The confirmation checkbox must be checked before the button activates. Also confirm that at least 1 account is selected in the Step 2 table.']),
    spacer(),
    errorBox(['"Partial failure — X records not updated"',
      'The result panel lists which records failed and the reason. Common causes: record locked by another user, a validation rule triggered, or insufficient permissions. Fix the cause and re-run for just the failed records, or update them manually in Salesforce.']),
    spacer(),
    noteBox(['To reverse a reassignment: backup CSVs in sf_backups/ contain the original Owner IDs.', 'Run the wizard again with the From and To reps swapped, or restore the original values via Salesforce Data Loader using the backup file.', 'See Guide 8 — Dry Run & Auto-Backup Safety for full recovery instructions.']),
    spacer(),
    rule(),

    h1('6. Related Guides'),
    relatedTable([3, 5, 7, 8]),
  ];
  return save(makeDoc(6, 'Territory Reassignment Wizard', 'v1.0', children), 'guide-06-territory-reassignment-wizard.docx');
}

// ══════════════════════════════════════════════════════════════════════════
// GUIDE 8 — Dry Run & Auto-Backup Safety
// ══════════════════════════════════════════════════════════════════════════
async function buildGuide8() {
  const children = [
    ...coverPage(8, 'Dry Run & Auto-Backup Safety', 'How to preview any operation before committing, and how to recover data using A.D.A.M.\'s automatic backup files', 'v1.0', 'March 2026'),

    h1('1. Overview'),
    body('Every operation in A.D.A.M. that writes data to Salesforce has two built-in safety layers: Dry Run mode and Auto-Backup. You should understand both before running any bulk operation.'),
    spacer(),
    infoTable([
      ['Dry Run Mode', 'Simulates the full operation without writing anything to Salesforce. Shows exactly what would change and how many records would be affected.'],
      ['Auto-Backup',  'Before any live write, A.D.A.M. automatically exports the current state of every affected record to a CSV file. This is your rollback option if something goes wrong.'],
    ]),
    spacer(),
    noteBox('Neither feature requires any setup. Dry Run Mode is a toggle in the left sidebar. Auto-Backup runs automatically on every live execution and cannot be turned off — by design.'),
    spacer(),
    rule(),

    h1('2. Dry Run Mode'),
    h2('How to enable it'),
    stepBox(1, 'Find the Dry Run toggle', ['Look in the bottom section of the A.D.A.M. left sidebar. The Dry Run Mode toggle is visible on every page of the tool.']),
    spacer(),
    stepBox(2, 'Toggle it ON', ['When ON, the toggle turns green and a yellow banner appears at the top of the screen: "DRY RUN MODE — no data will be written to Salesforce."']),
    spacer(),
    stepBox(3, 'Work through your operation as normal', ['Go through all steps of whichever feature you are using. When you reach the execute step, the button label changes to "Preview (Dry Run)" instead of "Execute".']),
    spacer(),
    stepBox(4, 'Review the dry run output', ['A.D.A.M. returns a simulated result showing expected record counts, which records would be included, and any issues it can detect in advance — without touching any data.']),
    spacer(),
    screenshot('Left sidebar — Dry Run Mode toggle ON (green). Yellow "DRY RUN MODE" banner at top of screen. Preview button visible.'),
    spacer(),
    warnBox('Dry Run Mode cannot catch every possible error. It simulates logic and counts but cannot predict Salesforce validation rule failures or record locks that only appear at write time. Always review the live execution result carefully too.'),
    spacer(),

    h2('Example dry run output'),
    adamBox([
      'DRY RUN  —  no data written to Salesforce',
      '',
      'Operation:             Territory Reassignment',
      'From:                  Alex Chen  →  To: Jamie Park',
      'Territory:             Territory 2',
      '',
      'Accounts to update:      17',
      'Contacts to update:      44',
      'Opportunities to update:  9   (open only)',
      '',
      'Excluded by user:         1   (Initech Ltd — manually deselected)',
      'Closed opps protected:    3   (hardcoded exclusion — never updated)',
    ]),
    spacer(),
    rule(),

    h1('3. Auto-Backup'),
    h2('What gets backed up and where'),
    body('Before every live write operation, A.D.A.M. exports the current state of every record it is about to change. One CSV file is created per object type.'),
    spacer(),
    infoTable([
      ['Backup folder',  'sf_backups/  inside the A.D.A.M. project directory on the server running the tool'],
      ['Subfolder name', '[operation-type]_[date]  e.g.  reassign_territory2_2026-03-03/'],
      ['File names',     '[Object]_backup_[timestamp].csv  e.g.  Account_backup_2026-03-03_14-22.csv'],
      ['What is saved',  'The record Id plus every field that will be modified — enough to restore original values'],
      ['Retention',      'Backup files are never deleted automatically. Clean them up manually when no longer needed.'],
    ]),
    spacer(),
    noteBox('Backups are created before the write runs. If an operation fails partway through, all three backup files still exist and cover all objects — even the ones that were not updated yet. You can always restore the full pre-operation state.'),
    spacer(),
    screenshot('sf_backups/ folder — subfolders per operation, each containing Account / Contact / Opportunity CSV files with timestamps'),
    spacer(),

    h2('How to restore records from a backup'),
    stepBox(1, 'Find the backup folder', ['Go to sf_backups/ in the A.D.A.M. project folder. Open the subfolder for the operation you want to reverse — it is named by operation type and date.']),
    spacer(),
    stepBox(2, 'Open the CSV file', ['Each file contains: record Id, the original field value (e.g. OwnerId), and a timestamp. Open in Excel to review the records before restoring.']),
    spacer(),
    stepBox(3, 'Restore via Data Loader (for large volumes)', [
      'Open Salesforce Data Loader on your computer.',
      'Choose Update and select the object (e.g. Account, Contact, or Opportunity).',
      'Map the Id column and the field you want to restore (e.g. OwnerId).',
      'Upload the backup CSV file.',
      'Data Loader will restore the original values for every record in the file.',
    ]),
    spacer(),
    stepBox(4, 'Restore via Salesforce UI (for small volumes)', ['For fewer than 10–20 records it is faster to update OwnerId manually using the Transfer Records tool in Salesforce Setup. Search for "Transfer Records" in the Setup Quick Find box.']),
    spacer(),
    warnBox('Restoring from a backup overwrites the current field values. If records have been legitimately updated since the backup was taken, restoring will undo those changes too. Always check the backup timestamp before proceeding.'),
    spacer(),
    rule(),

    h1('4. Worked Example'),
    h2('Recovering from a wrong-rep reassignment'),
    body('During a Territory 2 reassignment, the wrong outgoing rep was accidentally selected. Twenty-two accounts that should have stayed with their current owner were transferred to Jamie Park in error.'),
    spacer(),
    h3('Recovery steps'),
    stepBox(1, 'Find the backup', ['Open sf_backups/reassign_territory2_2026-03-03/. The file Account_backup_2026-03-03_14-22.csv contains the original OwnerId for all 22 accounts that were changed.']),
    spacer(),
    stepBox(2, 'Review the file', ['Open in Excel. Confirm the OwnerId column shows the correct original owner IDs for the 22 affected accounts.']),
    spacer(),
    stepBox(3, 'Restore via Data Loader', [
      'Open Salesforce Data Loader.',
      'Select Update, then Account.',
      'Map: Id column to Id, OwnerId column to OwnerId.',
      'Upload the backup CSV.',
      'All 22 accounts are restored to their original owners.',
    ]),
    spacer(),
    successBox([
      '22 Account records restored to original owners.',
      'Recovery completed via Data Loader backup restore.',
      'Total time: approximately 5 minutes.',
    ]),
    spacer(),
    rule(),

    h1('5. Troubleshooting'),
    errorBox(['"I cannot find the sf_backups folder"',
      'The backup folder is on the machine running A.D.A.M. If you are using the shared web interface, the folder is on the server — not on your local machine. Ask your Salesforce admin to retrieve the backup files for you.']),
    spacer(),
    errorBox(['"The dry run showed X records but the live run updated Y records"',
      'Records may have been created, modified, or locked between your dry run and live execution. Always execute promptly after reviewing a dry run. If counts differ significantly, review the live result panel carefully before relying on the output.']),
    spacer(),
    warnBox(['Backup CSV files are stored on the server running A.D.A.M.', 'If the server is reset or the project folder is deleted, backup history is lost.', 'For critical operations, copy backup CSV files to a shared drive or Teams folder immediately after running.']),
    spacer(),
    rule(),

    h1('6. Related Guides'),
    relatedTable([1, 3, 4, 6, 7]),
  ];
  return save(makeDoc(8, 'Dry Run & Auto-Backup Safety', 'v1.0', children), 'guide-08-dry-run-and-auto-backup.docx');
}

// ══════════════════════════════════════════════════════════════════════════
// RUN ALL
// ══════════════════════════════════════════════════════════════════════════
async function main() {
  console.log('\n  A.D.A.M. — Axonify Data & Administration Manager');
  console.log('  How-To Guide Series Builder\n');

  await buildSetupGuide();
  await buildMasterTemplate();
  await buildGuide1();
  await buildGuide6();
  await buildGuide8();

  console.log(`\n  All documents saved to:  ${OUT}/\n`);
}

main().catch(err => {
  console.error('\n  Build failed:', err.message);
  process.exit(1);
});
// Central data-testid registry for Shotvi
export const HOME = {
  emergentLink: "home-emergent-link",
};

export const LANDING = {
  root: "landing-root",
  navSignIn: "landing-nav-signin",
  navGetStarted: "landing-nav-getstarted",
  heroCta: "landing-hero-cta",
  heroSecondaryCta: "landing-hero-secondary-cta",
  featureCard: (id) => `landing-feature-${id}`,
  pricingCard: (id) => `landing-pricing-${id}`,
  pricingCta: (id) => `landing-pricing-cta-${id}`,
  footerCta: "landing-footer-cta",
};

export const AUTH = {
  root: "auth-root",
  tabSignIn: "auth-tab-signin",
  tabSignUp: "auth-tab-signup",
  email: "auth-email-input",
  password: "auth-password-input",
  name: "auth-name-input",
  submit: "auth-submit-button",
  googleBtn: "auth-google-button",
  backHome: "auth-back-home",
};

export const DASHBOARD = {
  root: "dashboard-root",
  newProject: "dashboard-new-project-button",
  projectCard: (id) => `dashboard-project-${id}`,
  projectOpen: (id) => `dashboard-project-open-${id}`,
  sidebarLink: (key) => `sidebar-link-${key}`,
  userMenu: "sidebar-user-menu",
};

export const UPLOAD = {
  root: "upload-root",
  modeFile: "upload-mode-file",
  modeUrl: "upload-mode-url",
  dropZone: "upload-drop-zone",
  fileInput: "upload-file-input",
  urlInput: "upload-url-input",
  languageSelect: "upload-language-select",
  languageOption: (code) => `upload-language-${code}`,
  submit: "upload-start-button",
  progress: "upload-progress",
};

export const CLIPS = {
  root: "clips-root",
  backBtn: "clips-back-button",
  card: (id) => `clip-card-${id}`,
  edit: (id) => `clip-edit-${id}`,
  preview: (id) => `clip-preview-${id}`,
  export: (id) => `clip-export-${id}`,
};

export const EDITOR = {
  root: "editor-root",
  backBtn: "editor-back-button",
  exportBtn: "editor-export-button",

  // Clip list panel
  clipListItem: (id) => `editor-clip-${id}`,

  // Transport / Timeline
  canvas: "editor-canvas",
  canvasStage: "editor-canvas-stage",
  playBtn: "editor-play-button",
  splitBtn: "editor-split-button",
  seekBackBtn: "editor-seek-back",
  seekFwdBtn: "editor-seek-fwd",
  timelineWord: (idx) => `timeline-word-${idx}`,
  timelinePlayhead: "timeline-playhead",

  // Inspector tabs
  tabStyle: "editor-tab-style",
  tabMusic: "editor-tab-music",
  tabExport: "editor-tab-export",

  // Style inspector
  presetBtn: (id) => `editor-preset-${id}`,
  fontSelect: "editor-font-select",
  sizeSlider: "editor-size-slider",
  positionBtn: (pos) => `editor-position-${pos}`, // legacy — kept for BC
  positionPresetBtn: (name) => `editor-pos-preset-${name}`,
  animationBtn: (a) => `editor-animation-${a}`,
  wordHighlightToggle: "editor-word-highlight-toggle",
  pillToggle: "editor-pill-toggle",
  pillColor: "editor-pill-color",
  pillOpacity: "editor-pill-opacity",
  pillPadding: "editor-pill-padding",
  pillRadius: "editor-pill-radius",

  // Music
  musicItem: (id) => `editor-music-${id}`,

  // Canvas toolbar
  zoomIn: "editor-zoom-in",
  zoomOut: "editor-zoom-out",
  zoomFit: "editor-zoom-fit",
  zoomLevel: "editor-zoom-level",
  safeZoneToggle: "editor-safe-zone-toggle",
  safeZoneOption: (mode) => `editor-safe-zone-${mode}`,
  addElementMenu: "editor-add-element-menu",
  addElementOption: (type) => `editor-add-element-${type}`,

  // Canvas elements
  element: (id) => `canvas-element-${id}`,
  elementSelectable: (id) => `canvas-element-select-${id}`,
  transformHandle: (pos) => `transform-handle-${pos}`, // tl|tr|bl|br|rot
  transformBox: "transform-box",

  // Elements panel
  elementsList: "editor-elements-list",
  elementRow: (id) => `elements-row-${id}`,
  elementVisibility: (id) => `elements-visibility-${id}`,
  elementForward: (id) => `elements-forward-${id}`,
  elementBackward: (id) => `elements-backward-${id}`,
  elementDelete: (id) => `elements-delete-${id}`,
};

export const EXPORT = {
  root: "export-root",
  resolutionBtn: (v) => `export-resolution-${v}`,
  formatBtn: (v) => `export-format-${v}`,
  burnToggle: "export-burn-toggle",
  aspectBtn: (v) => `export-aspect-${v}`,
  startBtn: "export-start-button",
  download: "export-download-button",
  generateMetadata: "export-generate-metadata-button",
};

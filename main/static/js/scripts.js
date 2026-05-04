const translations = {
  en: {
    navLabel: "Primary navigation",
    searchProducts: "Search Exabay products",
    navSearchPlaceholder: "Search trusted products, brands, sellers",
    heroSearchPlaceholder: "What are you looking for today?",
    search: "Search",
    viewCart: "View cart",
    openProfile: "Open profile",
    switchLanguage: "Switch language to Swahili",
    heroEyebrow: "Trust-first marketplace",
    heroTitle: "Buy from verified sellers with confidence",
    heroCopy: "Discover everyday essentials, electronics, fashion, and home goods with visible seller verification on every listing.",
    popularCategories: "Popular categories",
    catElectronics: "Electronics",
    catHome: "Home",
    catFashion: "Fashion",
    catBeauty: "Beauty",
    trustSummary: "Marketplace trust summary",
    trustSignalTitle: "Verified seller signals",
    trustSignalCopy: "Business checks, document status, and order metrics shown before you buy.",
    averageRating: "Average seller rating",
    completedTrustedOrders: "Completed trusted orders",
    featuredMarketplace: "Featured marketplace",
    productsTitle: "Products from credible sellers",
    filterSellers: "Filter sellers",
    seller: "Seller",
    viewSellerTrust: "View Seller Trust",
    addToCart: "Add to Cart",
    viewDetails: "View Details",
    inStock: "In Stock",
    lowStock: "Low Stock",
    verified: "Verified",
    pending: "Pending",
    unverified: "Unverified",
    sellerTrustProfile: "Seller trust profile",
    verificationStatus: "Verification Status",
    documents: "Documents",
    sensitivePreviewsHidden: "Sensitive previews hidden",
    sellerMetrics: "Seller Metrics",
    totalProducts: "Total products",
    completedOrders: "Completed orders",
    rating: "Rating",
    closeTrustDetails: "Close seller trust details",
    viewDocument: "View Document",
    stars: "stars",
    businessLicense: "Business License",
    idVerification: "ID Verification",
    storeRegistration: "Store Registration",
    noProductsTitle: "No products available",
    noProductsCopy: "Please check back soon for trusted marketplace listings.",
    submitted: "Submitted",
    missing: "Missing",
    trustCopyVerified: "This seller has been verified by Exabay and meets our trust standards.",
    trustCopyPending: "This seller has submitted the required trust profile information and is waiting for Exabay review.",
    trustCopyUnverified: "This seller has not completed Exabay's verification checks yet."
  },
  sw: {
    navLabel: "Urambazaji mkuu",
    searchProducts: "Tafuta bidhaa za Exabay",
    navSearchPlaceholder: "Tafuta bidhaa, chapa, na wauzaji wa kuaminika",
    heroSearchPlaceholder: "Unatafuta nini leo?",
    search: "Tafuta",
    viewCart: "Tazama kikapu",
    openProfile: "Fungua wasifu",
    switchLanguage: "Badilisha lugha kwenda Kiingereza",
    heroEyebrow: "Soko linalotanguliza uaminifu",
    heroTitle: "Nunua kutoka kwa wauzaji waliothibitishwa kwa kujiamini",
    heroCopy: "Gundua mahitaji ya kila siku, elektroniki, mitindo, na bidhaa za nyumbani zikiwa na uthibitisho wa muuzaji kwenye kila tangazo.",
    popularCategories: "Makundi maarufu",
    catElectronics: "Elektroniki",
    catHome: "Nyumbani",
    catFashion: "Mitindo",
    catBeauty: "Urembo",
    trustSummary: "Muhtasari wa uaminifu wa soko",
    trustSignalTitle: "Ishara za muuzaji aliyethibitishwa",
    trustSignalCopy: "Ukaguzi wa biashara, hali ya nyaraka, na takwimu za oda huonekana kabla ya kununua.",
    averageRating: "Wastani wa alama za wauzaji",
    completedTrustedOrders: "Oda salama zilizokamilika",
    featuredMarketplace: "Soko lililoangaziwa",
    productsTitle: "Bidhaa kutoka kwa wauzaji wa kuaminika",
    filterSellers: "Chuja wauzaji",
    seller: "Muuzaji",
    viewSellerTrust: "Tazama Uaminifu wa Muuzaji",
    addToCart: "Ongeza Kikapuni",
    viewDetails: "Tazama Maelezo",
    inStock: "Ipo dukani",
    lowStock: "Inakaribia kuisha",
    verified: "Imethibitishwa",
    pending: "Inasubiri",
    unverified: "Haijathibitishwa",
    sellerTrustProfile: "Wasifu wa uaminifu wa muuzaji",
    verificationStatus: "Hali ya Uthibitisho",
    documents: "Nyaraka",
    sensitivePreviewsHidden: "Muonekano wa taarifa nyeti umefichwa",
    sellerMetrics: "Takwimu za Muuzaji",
    totalProducts: "Jumla ya bidhaa",
    completedOrders: "Oda zilizokamilika",
    rating: "Alama",
    closeTrustDetails: "Funga maelezo ya uaminifu wa muuzaji",
    viewDocument: "Tazama Nyaraka",
    stars: "nyota",
    businessLicense: "Leseni ya Biashara",
    idVerification: "Uthibitisho wa Kitambulisho",
    storeRegistration: "Usajili wa Duka",
    noProductsTitle: "Hakuna bidhaa zilizopo",
    noProductsCopy: "Tafadhali rudi tena hivi karibuni kwa matangazo ya soko la kuaminika.",
    submitted: "Imewasilishwa",
    missing: "Haipo",
    trustCopyVerified: "Muuzaji huyu amethibitishwa na Exabay na anakidhi viwango vyetu vya uaminifu.",
    trustCopyPending: "Muuzaji huyu amewasilisha taarifa muhimu za wasifu wa uaminifu na anasubiri ukaguzi wa Exabay.",
    trustCopyUnverified: "Muuzaji huyu bado hajakamilisha ukaguzi wa uthibitisho wa Exabay."
  }
};

const modal = document.querySelector("#seller-modal");
const modalDialog = modal.querySelector(".modal__dialog");
const closeTriggers = modal.querySelectorAll("[data-modal-close]");
const languageToggle = document.querySelector("#language-toggle");
const productGrid = document.querySelector("#product-grid");
let currentLanguage = "en";
let activeCard = null;
let lastFocusedElement = null;

const statusMeta = {
  verified: { icon: "OK", className: "status-badge--verified", labelKey: "verified" },
  pending: { icon: "!", className: "status-badge--pending", labelKey: "pending" },
  unverified: { icon: "X", className: "status-badge--unverified", labelKey: "unverified" }
};

function t(key) {
  return translations[currentLanguage][key] || translations.en[key] || key;
}

function formatNumber(value) {
  const number = Number(value || 0);
  return new Intl.NumberFormat(currentLanguage === "sw" ? "sw-TZ" : "en-US").format(number);
}

function translateDocumentStatus(status) {
  const normalized = String(status || "").toLowerCase();
  if (normalized === "submitted") return t("submitted");
  if (normalized === "missing") return t("missing");
  return status || t("missing");
}

function getTrustCopy(statusKey, fallback) {
  const key = `trustCopy${statusKey.charAt(0).toUpperCase()}${statusKey.slice(1)}`;
  return t(key) || fallback;
}

function applyStaticTranslations() {
  document.documentElement.lang = currentLanguage === "sw" ? "sw" : "en";
  document.documentElement.dataset.language = currentLanguage;

  document.querySelectorAll("[data-i18n]").forEach((element) => {
    element.textContent = t(element.dataset.i18n);
  });

  document.querySelectorAll("[data-i18n-attr]").forEach((element) => {
    element.dataset.i18nAttr.split(",").forEach((pair) => {
      const [attribute, key] = pair.split(":").map((part) => part.trim());
      element.setAttribute(attribute, t(key));
    });
  });

  languageToggle.setAttribute("aria-label", t("switchLanguage"));
  languageToggle.setAttribute("aria-pressed", String(currentLanguage === "sw"));
  languageToggle.querySelector(".language-toggle__option--sw").classList.toggle("is-active", currentLanguage === "sw");
  languageToggle.querySelector(".language-toggle__option--en").classList.toggle("is-active", currentLanguage === "en");
}

function applyCardTranslations() {
  document.querySelectorAll("[data-card-i18n]").forEach((element) => {
    element.textContent = t(element.dataset.cardI18n);
  });

  document.querySelectorAll("[data-stock-key]").forEach((element) => {
    element.textContent = t(element.dataset.stockKey);
  });

  document.querySelectorAll("[data-status-key]").forEach((element) => {
    const status = statusMeta[element.dataset.statusKey];
    element.textContent = `${status.icon} ${t(status.labelKey)}`;
  });
}

function getDocumentsFromCard(card) {
  return [
    {
      label: t("businessLicense"),
      file: card.dataset.licenseDocument,
      status: translateDocumentStatus(card.dataset.licenseStatus)
    },
    {
      label: t("idVerification"),
      file: card.dataset.idDocument,
      status: translateDocumentStatus(card.dataset.idStatus)
    },
    {
      label: t("storeRegistration"),
      file: card.dataset.storeDocument,
      status: translateDocumentStatus(card.dataset.storeStatus)
    }
  ];
}

function renderSellerModal(card) {
  const statusKey = card.dataset.trustStatus || "unverified";
  const status = statusMeta[statusKey];

  document.querySelector("#seller-modal-title").textContent = card.dataset.sellerName;
  document.querySelector("#seller-business").textContent = card.dataset.businessName;

  const statusBadge = document.querySelector("#modal-status-badge");
  statusBadge.className = `status-badge ${status.className}`;
  statusBadge.textContent = `${status.icon} ${t(status.labelKey)}`;
  const trustCopy = getTrustCopy(statusKey, card.dataset.trustCopy);
  document.querySelector("#modal-status-copy").textContent = trustCopy;

  document.querySelector("#documents-list").innerHTML = getDocumentsFromCard(card).map((documentItem) => `
    <div class="document-item">
      <div>
        <div class="document-item__name">${documentItem.label}</div>
        <div class="document-item__status">${documentItem.file} - ${documentItem.status}</div>
      </div>
      <button class="btn btn--outline" type="button">${t("viewDocument")}</button>
    </div>
  `).join("");

  document.querySelector("#metric-products").textContent = formatNumber(card.dataset.totalProducts);
  document.querySelector("#metric-orders").textContent = formatNumber(card.dataset.completedOrders);
  document.querySelector("#metric-rating").textContent = `${card.dataset.rating || "4.8"} ${t("stars")}`;
  document.querySelector("#trust-message-copy").textContent = trustCopy;
}

function openSellerModal(card) {
  activeCard = card;
  lastFocusedElement = document.activeElement;
  renderSellerModal(card);

  modal.classList.add("is-open");
  modal.setAttribute("aria-hidden", "false");
  document.body.classList.add("modal-lock");
  modalDialog.focus();
}

function closeSellerModal() {
  modal.classList.remove("is-open");
  modal.setAttribute("aria-hidden", "true");
  document.body.classList.remove("modal-lock");
  activeCard = null;

  if (lastFocusedElement) {
    lastFocusedElement.focus();
  }
}

function setLanguage(language) {
  currentLanguage = language;
  applyStaticTranslations();
  applyCardTranslations();

  if (modal.classList.contains("is-open") && activeCard) {
    renderSellerModal(activeCard);
  }
}

productGrid.addEventListener("click", (event) => {
  const trigger = event.target.closest("[data-seller-trigger]");
  if (!trigger) return;

  const card = trigger.closest(".product-card");
  if (card) {
    openSellerModal(card);
  }
});

productGrid.querySelectorAll(".product-card").forEach((card) => {
  card.addEventListener("pointerenter", () => card.classList.add("is-hovered"));
  card.addEventListener("pointerleave", () => card.classList.remove("is-hovered"));
});

closeTriggers.forEach((trigger) => {
  trigger.addEventListener("click", closeSellerModal);
});

languageToggle.addEventListener("click", () => {
  setLanguage(currentLanguage === "en" ? "sw" : "en");
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && modal.classList.contains("is-open")) {
    closeSellerModal();
  }
});

setLanguage("en");

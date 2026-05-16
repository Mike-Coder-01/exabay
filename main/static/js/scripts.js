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
    taxClearance: "Tax Clearance Document",
    noProductsTitle: "No products available",
    noProductsCopy: "Please check back soon for trusted marketplace listings.",
    submitted: "Submitted",
    missing: "Missing",
    unavailable: "Unavailable",
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
    taxClearance: "Nyaraka ya Ulipaji Kodi",
    noProductsTitle: "Hakuna bidhaa zilizopo",
    noProductsCopy: "Tafadhali rudi tena hivi karibuni kwa matangazo ya soko la kuaminika.",
    submitted: "Imewasilishwa",
    missing: "Haipo",
    unavailable: "Haipatikani",
    trustCopyVerified: "Muuzaji huyu amethibitishwa na Exabay na anakidhi viwango vyetu vya uaminifu.",
    trustCopyPending: "Muuzaji huyu amewasilisha taarifa muhimu za wasifu wa uaminifu na anasubiri ukaguzi wa Exabay.",
    trustCopyUnverified: "Muuzaji huyu bado hajakamilisha ukaguzi wa uthibitisho wa Exabay."
  }
};

const modal = document.querySelector("#seller-modal");
const modalDialog = modal ? modal.querySelector(".modal__dialog") : null;
const closeTriggers = modal ? modal.querySelectorAll("[data-modal-close]") : [];
const languageToggle = document.querySelector("#language-toggle");
const productGrid = document.querySelector("#product-grid");
const cartPage = document.querySelector("[data-cart-page]");
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

  if (!languageToggle) return;

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
      status: translateDocumentStatus(card.dataset.licenseStatus),
      url: card.dataset.licenseUrl
    },
    {
      label: t("taxClearance"),
      file: card.dataset.taxDocument,
      status: translateDocumentStatus(card.dataset.taxStatus),
      url: card.dataset.taxUrl
    },
    {
      label: t("idVerification"),
      file: card.dataset.idDocument,
      status: translateDocumentStatus(card.dataset.idStatus),
      url: ""
    },
    {
      label: t("storeRegistration"),
      file: card.dataset.storeDocument,
      status: translateDocumentStatus(card.dataset.storeStatus),
      url: ""
    }
  ];
}

function renderSellerModal(card) {
  if (!modal) return;

  const statusKey = card.dataset.trustStatus || "unverified";
  const status = statusMeta[statusKey];

  document.querySelector("#seller-modal-title").textContent = card.dataset.sellerName;
  document.querySelector("#seller-business").textContent = card.dataset.businessName;

  const statusBadge = document.querySelector("#modal-status-badge");
  statusBadge.className = `status-badge ${status.className}`;
  statusBadge.textContent = `${status.icon} ${t(status.labelKey)}`;
  const trustCopy = getTrustCopy(statusKey, card.dataset.trustCopy);
  document.querySelector("#modal-status-copy").textContent = trustCopy;

  document.querySelector("#documents-list").innerHTML = getDocumentsFromCard(card).map((documentItem) => {
    const action = documentItem.url
      ? `<a class="btn btn--outline" href="${documentItem.url}" target="_blank" rel="noopener">${t("viewDocument")}</a>`
      : `<button class="btn btn--outline" type="button" disabled>${t("unavailable")}</button>`;

    return `
      <div class="document-item">
        <div>
          <div class="document-item__name">${documentItem.label}</div>
          <div class="document-item__status">${documentItem.file} - ${documentItem.status}</div>
        </div>
        ${action}
      </div>
    `;
  }).join("");

  document.querySelector("#metric-products").textContent = formatNumber(card.dataset.totalProducts);
  document.querySelector("#metric-orders").textContent = formatNumber(card.dataset.completedOrders);
  document.querySelector("#metric-rating").textContent = `${card.dataset.rating || "4.8"} ${t("stars")}`;
  document.querySelector("#trust-message-copy").textContent = trustCopy;
}

function openSellerModal(card) {
  if (!modal || !modalDialog) return;

  activeCard = card;
  lastFocusedElement = document.activeElement;
  renderSellerModal(card);

  modal.classList.add("is-open");
  modal.setAttribute("aria-hidden", "false");
  document.body.classList.add("modal-lock");
  modalDialog.focus();
}

function closeSellerModal() {
  if (!modal) return;

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

  if (modal && modal.classList.contains("is-open") && activeCard) {
    renderSellerModal(activeCard);
  }
}

if (productGrid) {
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
}

closeTriggers.forEach((trigger) => {
  trigger.addEventListener("click", closeSellerModal);
});

if (languageToggle) {
  languageToggle.addEventListener("click", () => {
    setLanguage(currentLanguage === "en" ? "sw" : "en");
  });
}

function parseMoney(value) {
  return Number.parseFloat(String(value || "0").replace(/,/g, "")) || 0;
}

function formatMoney(value) {
  return value.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  });
}

function updateCartTotals() {
  if (!cartPage) return;

  let itemCount = 0;
  let cartTotal = 0;

  cartPage.querySelectorAll("[data-cart-item]").forEach((item) => {
    const price = parseMoney(item.dataset.price);
    const quantityInput = item.querySelector("[data-cart-quantity]");
    const quantity = Math.max(1, Number.parseInt(quantityInput.value, 10) || 1);
    const subtotal = price * quantity;

    item.dataset.quantity = String(quantity);
    quantityInput.value = String(quantity);
    item.querySelector("[data-cart-subtotal]").textContent = formatMoney(subtotal);

    itemCount += quantity;
    cartTotal += subtotal;
  });

  cartPage.querySelectorAll("[data-cart-total], [data-cart-grand-total]").forEach((element) => {
    element.textContent = formatMoney(cartTotal);
  });

  const countElement = cartPage.querySelector("[data-cart-count]");
  if (countElement) {
    countElement.textContent = `${itemCount} item${itemCount === 1 ? "" : "s"}`;
  }
}

function queueCartAjax(item, action) {
  const url = action === "remove" ? item.dataset.removeUrl : item.dataset.updateUrl;
  item.dataset.pendingAction = action;
  item.dataset.pendingUrl = url || "";
}

function initializeCartPage() {
  if (!cartPage) return;

  cartPage.addEventListener("click", (event) => {
    const item = event.target.closest("[data-cart-item]");
    if (!item) return;

    const input = item.querySelector("[data-cart-quantity]");
    const max = Number.parseInt(input.getAttribute("max"), 10) || Infinity;
    const currentValue = Number.parseInt(input.value, 10) || 1;

    if (event.target.closest("[data-cart-increase]")) {
      input.value = String(Math.min(max, currentValue + 1));
      queueCartAjax(item, "update");
      updateCartTotals();
    }

    if (event.target.closest("[data-cart-decrease]")) {
      input.value = String(Math.max(1, currentValue - 1));
      queueCartAjax(item, "update");
      updateCartTotals();
    }

    if (event.target.closest("[data-cart-remove]")) {
      queueCartAjax(item, "remove");
      item.classList.add("is-removing");
      window.setTimeout(() => {
        item.remove();
        updateCartTotals();
      }, 160);
    }
  });

  cartPage.addEventListener("change", (event) => {
    if (!event.target.matches("[data-cart-quantity]")) return;

    const input = event.target;
    const item = input.closest("[data-cart-item]");
    const max = Number.parseInt(input.getAttribute("max"), 10) || Infinity;
    const value = Number.parseInt(input.value, 10) || 1;
    input.value = String(Math.min(max, Math.max(1, value)));
    queueCartAjax(item, "update");
    updateCartTotals();
  });

  updateCartTotals();
}


function initializeAuthRoleForms() {
  document.querySelectorAll("[data-auth-role-form]").forEach((form) => {
    const roleInputs = form.querySelectorAll('input[name="role"]');
    const sellerFields = form.querySelector("[data-seller-fields]");

    function syncRoleState() {
      const selectedRole = form.querySelector('input[name="role"]:checked')?.value || "buyer";

      roleInputs.forEach((input) => {
        const card = input.closest(".auth-role__card");
        if (card) {
          card.classList.toggle("is-selected", input.checked);
        }
      });

      if (sellerFields) {
        sellerFields.classList.toggle("is-hidden", selectedRole !== "seller");
      }
    }

    roleInputs.forEach((input) => {
      input.addEventListener("change", syncRoleState);
    });

    syncRoleState();
  });
}

function initializeFooterNewsletter() {
  document.querySelectorAll("[data-footer-newsletter]").forEach((form) => {
    const input = form.querySelector('input[type="email"]');
    const status = form.querySelector("[data-footer-newsletter-status]");

    form.addEventListener("submit", (event) => {
      event.preventDefault();

      if (!input.checkValidity()) {
        input.reportValidity();
        return;
      }

      status.textContent = "Thanks. You are on the Exabay updates list.";
      form.reset();
    });
  });
}

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && modal && modal.classList.contains("is-open")) {
    closeSellerModal();
  }
});

setLanguage("en");
initializeCartPage();
initializeAuthRoleForms();
initializeFooterNewsletter();


fetch(item.dataset.updateUrl, {
  method: "POST",
  headers: {
    "X-CSRFToken": csrfToken,
    "X-Requested-With": "XMLHttpRequest"
  },
  body: new URLSearchParams({
    quantity: input.value
  })
});

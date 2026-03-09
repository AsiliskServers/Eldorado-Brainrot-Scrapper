const state = {
  rows: [],
  latestStamp: null,
  search: "",
  pageSize: 100,
  currentPage: 1,
  scrapeState: null,
  previousRunning: false,
  filters: {
    rarity: "all",
    speed: "all",
    price: "all",
  },
  sorts: [],
};

const PRICE_FILTERS = [
  { key: "all", label: "Tous" },
  { key: "0-50", label: "0-50 EUR" },
  { key: "50-100", label: "50-100 EUR" },
  { key: "100-500", label: "100-500 EUR" },
  { key: "500+", label: "500+ EUR" },
];

const refs = {
  scrapeButton: document.getElementById("scrapeButton"),
  clearButton: document.getElementById("clearButton"),
  refreshButton: document.getElementById("refreshButton"),
  searchInput: document.getElementById("searchInput"),
  raritySelect: document.getElementById("raritySelect"),
  speedSelect: document.getElementById("speedSelect"),
  priceSelect: document.getElementById("priceSelect"),
  sortPriceText: document.getElementById("sortPriceText"),
  sortQuantityText: document.getElementById("sortQuantityText"),
  sortSpeedText: document.getElementById("sortSpeedText"),
  prevPageButton: document.getElementById("prevPageButton"),
  nextPageButton: document.getElementById("nextPageButton"),
  pageInfo: document.getElementById("pageInfo"),
  offersRange: document.getElementById("offersRange"),
  lastUpdate: document.getElementById("lastUpdate"),
  offerCount: document.getElementById("offerCount"),
  minPrice: document.getElementById("minPrice"),
  maxPrice: document.getElementById("maxPrice"),
  offersTbody: document.getElementById("offersTbody"),
  toast: document.getElementById("toast"),
  progressLabel: document.getElementById("progressLabel"),
  progressValue: document.getElementById("progressValue"),
  progressBar: document.getElementById("progressBar"),
  progressMeta: document.getElementById("progressMeta"),
  satelliteHealthBadge: document.getElementById("satelliteHealthBadge"),
  satelliteStatusText: document.getElementById("satelliteStatusText"),
};

const SORT_CONTROLS = [
  { field: "price", label: "Prix", ref: refs.sortPriceText },
  { field: "quantity", label: "Quantite", ref: refs.sortQuantityText },
  { field: "speed", label: "Vitesse", ref: refs.sortSpeedText },
];

async function requestJSON(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.error || `Request failed: ${response.status}`);
  }
  return response.json();
}

function euro(value) {
  const amount = Number(value);
  if (!Number.isFinite(amount)) return "-";
  return amount.toLocaleString("fr-FR", { style: "currency", currency: "EUR" });
}

function decimal(value) {
  const amount = Number(value);
  if (!Number.isFinite(amount)) return "-";
  return amount.toLocaleString("fr-FR", { maximumFractionDigits: 2 });
}

function showToast(message, timeoutMs = 2400) {
  refs.toast.textContent = message;
  refs.toast.classList.remove("hidden");
  window.setTimeout(() => refs.toast.classList.add("hidden"), timeoutMs);
}

function escapeHTML(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatDate(isoString) {
  const date = new Date(isoString);
  if (Number.isNaN(date.getTime())) return isoString || "-";
  return date.toLocaleString("fr-FR", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    timeZone: "UTC",
    timeZoneName: "short",
  });
}

function toSortableNumber(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : Number.NaN;
}

function getRowSpeedKey(row) {
  if (row.speed_bucket_raw) return String(row.speed_bucket_raw);
  if (row.speed_exact_value !== null && row.speed_exact_value !== undefined && row.speed_exact_unit) {
    return `Exact ${row.speed_exact_unit}`;
  }
  return "Sans vitesse";
}

function formatSpeed(row) {
  const exactValue = toSortableNumber(row.speed_exact_value);
  if (Number.isFinite(exactValue) && row.speed_exact_unit) {
    return `${exactValue.toLocaleString("fr-FR", { maximumFractionDigits: 3 })} ${row.speed_exact_unit}`;
  }
  return row.speed_bucket_raw ? String(row.speed_bucket_raw) : "-";
}

function getSortValue(row, field) {
  if (field === "price") return toSortableNumber(row.price_amount);
  if (field === "quantity") return toSortableNumber(row.quantity);
  if (field === "speed") {
    const exact = toSortableNumber(row.speed_exact_mps);
    return Number.isFinite(exact) ? exact : toSortableNumber(row.speed_bucket_min_mps);
  }
  return Number.NaN;
}

function compareValues(aValue, bValue, direction) {
  const aValid = Number.isFinite(aValue);
  const bValid = Number.isFinite(bValue);
  if (!aValid && !bValid) return 0;
  if (!aValid) return 1;
  if (!bValid) return -1;
  if (aValue === bValue) return 0;
  const asc = aValue > bValue ? 1 : -1;
  return direction === "asc" ? asc : -asc;
}

function sortRows(rows) {
  if (!state.sorts.length) return rows;
  const sorted = rows.slice();
  sorted.sort((a, b) => {
    for (const sortRule of state.sorts) {
      const cmp = compareValues(getSortValue(a, sortRule.field), getSortValue(b, sortRule.field), sortRule.direction);
      if (cmp !== 0) return cmp;
    }
    return 0;
  });
  return sorted;
}

function rowMatchesSearch(row, query) {
  if (!query) return true;
  const haystack = [
    row.offer_title,
    row.item_name,
    row.rarity,
    row.seller_username,
    row.speed_bucket_raw,
    row.speed_exact_raw,
    row.speed_exact_unit,
  ]
    .map((value) => String(value ?? "").toLowerCase())
    .join(" ");
  return haystack.includes(query);
}

function rowMatchesPrice(row, priceFilter) {
  if (priceFilter === "all") return true;
  const value = toSortableNumber(row.price_amount);
  if (!Number.isFinite(value)) return false;
  if (priceFilter === "0-50") return value >= 0 && value < 50;
  if (priceFilter === "50-100") return value >= 50 && value < 100;
  if (priceFilter === "100-500") return value >= 100 && value < 500;
  if (priceFilter === "500+") return value >= 500;
  return true;
}

function getFilteredRows() {
  const query = state.search.trim().toLowerCase();
  return sortRows(
    state.rows.filter((row) => {
      if (!rowMatchesSearch(row, query)) return false;
      if (state.filters.rarity !== "all" && String(row.rarity || "") !== state.filters.rarity) return false;
      if (state.filters.speed !== "all" && getRowSpeedKey(row) !== state.filters.speed) return false;
      if (!rowMatchesPrice(row, state.filters.price)) return false;
      return true;
    })
  );
}

function renderStats() {
  refs.lastUpdate.textContent = state.latestStamp ? formatDate(state.latestStamp) : "-";
  refs.offerCount.textContent = String(state.rows.length);

  const prices = state.rows.map((row) => toSortableNumber(row.price_amount)).filter((value) => Number.isFinite(value));
  refs.minPrice.textContent = prices.length ? euro(Math.min(...prices)) : "-";
  refs.maxPrice.textContent = prices.length ? euro(Math.max(...prices)) : "-";
}

function renderOffers() {
  const filteredRows = getFilteredRows();
  const totalRows = filteredRows.length;
  const totalPages = Math.max(1, Math.ceil(totalRows / state.pageSize));
  state.currentPage = Math.min(Math.max(1, state.currentPage), totalPages);

  const startIndex = (state.currentPage - 1) * state.pageSize;
  const pageRows = filteredRows.slice(startIndex, startIndex + state.pageSize);
  const rangeStart = totalRows === 0 ? 0 : startIndex + 1;
  const rangeEnd = totalRows === 0 ? 0 : startIndex + pageRows.length;

  refs.offersRange.textContent = `${rangeStart}-${rangeEnd} / ${totalRows}`;
  refs.pageInfo.textContent = `Page ${state.currentPage} / ${totalPages} (${state.pageSize}/page)`;
  refs.prevPageButton.disabled = state.currentPage <= 1;
  refs.nextPageButton.disabled = state.currentPage >= totalPages;

  refs.offersTbody.innerHTML = pageRows
    .map((row) => {
      const verified = row.seller_verified
        ? '<span class="pill pill-yes">Verifie</span>'
        : '<span class="pill pill-no">Non verifie</span>';
      const link = row.offer_url
        ? `<a class="link-btn" href="${escapeHTML(row.offer_url)}" target="_blank" rel="noopener noreferrer">Voir</a>`
        : '<span class="pill pill-no">N/A</span>';

      return `
        <tr>
          <td>${escapeHTML(row.offer_title || "-")}</td>
          <td>${escapeHTML(row.item_name || row.offer_title || "-")}</td>
          <td>${escapeHTML(row.rarity || "-")}</td>
          <td>${escapeHTML(formatSpeed(row))}</td>
          <td>${euro(row.price_amount)}</td>
          <td>${decimal(row.quantity)}</td>
          <td>
            <div>${escapeHTML(row.seller_username || "-")}</div>
            <div>${verified}</div>
          </td>
          <td>${decimal(row.feedback_score)}</td>
          <td>${link}</td>
        </tr>
      `;
    })
    .join("") || '<tr><td colspan="9">Aucune offre pour ce filtre.</td></tr>';
}

function setSelectOptions(selectElement, items, selectedKey) {
  selectElement.innerHTML = items
    .map((item) => `<option value="${escapeHTML(item.key)}">${escapeHTML(item.label)}</option>`)
    .join("");

  const exists = items.some((item) => item.key === selectedKey);
  selectElement.value = exists ? selectedKey : "all";
  return exists ? selectedKey : "all";
}

function renderFilterSelects() {
  const rarityValues = Array.from(
    new Set(state.rows.map((row) => String(row.rarity || "")).filter((value) => value !== ""))
  ).sort((a, b) => a.localeCompare(b, "fr"));
  const speedValues = Array.from(new Set(state.rows.map((row) => getRowSpeedKey(row)))).sort((a, b) =>
    a.localeCompare(b, "fr")
  );

  state.filters.rarity = setSelectOptions(
    refs.raritySelect,
    [{ key: "all", label: "Toutes" }, ...rarityValues.map((value) => ({ key: value, label: value }))],
    state.filters.rarity
  );

  state.filters.speed = setSelectOptions(
    refs.speedSelect,
    [{ key: "all", label: "Toutes" }, ...speedValues.map((value) => ({ key: value, label: value }))],
    state.filters.speed
  );

  state.filters.price = setSelectOptions(refs.priceSelect, PRICE_FILTERS, state.filters.price);
}

function renderSortTexts() {
  for (const control of SORT_CONTROLS) {
    if (!control.ref) continue;
    const index = state.sorts.findIndex((sortRule) => sortRule.field === control.field);
    if (index < 0) {
      control.ref.textContent = control.label;
      control.ref.classList.remove("active");
      continue;
    }

    const direction = state.sorts[index].direction;
    const marker = direction === "asc" ? "^" : "v";
    control.ref.textContent = `${control.label} ${index + 1}${marker}`;
    control.ref.classList.add("active");
  }
}

function renderAllFilters() {
  renderFilterSelects();
  renderSortTexts();
}

function cycleSort(field) {
  const index = state.sorts.findIndex((sortRule) => sortRule.field === field);

  if (index < 0) {
    state.sorts = [{ field, direction: "asc" }, ...state.sorts];
  } else if (state.sorts[index].direction === "asc") {
    const remaining = state.sorts.filter((_, i) => i !== index);
    state.sorts = [{ field, direction: "desc" }, ...remaining];
  } else {
    state.sorts = state.sorts.filter((_, i) => i !== index);
  }

  state.currentPage = 1;
  renderSortTexts();
  renderOffers();
}

function resetRowsState() {
  state.rows = [];
  state.latestStamp = null;
  state.currentPage = 1;
  state.filters = { rarity: "all", speed: "all", price: "all" };
  state.sorts = [];
}

function setSatelliteBadge(text, ok) {
  refs.satelliteHealthBadge.textContent = text;
  refs.satelliteHealthBadge.classList.remove("pill-yes", "pill-no");
  refs.satelliteHealthBadge.classList.add(ok ? "pill-yes" : "pill-no");
}

function renderScrapeState() {
  const scrape = state.scrapeState || {};
  const running = Boolean(scrape.running);
  const progress = Math.max(0, Math.min(100, Number(scrape.progress_percent || 0)));

  refs.progressBar.style.width = `${progress}%`;
  refs.progressValue.textContent = `${progress.toFixed(1)}%`;

  if (running) {
    refs.progressLabel.textContent = "Scrape en cours (toutes pages)";
    refs.progressMeta.textContent = `Page ${scrape.current_page || 0} / ${scrape.total_pages || "?"} - ${scrape.rows_collected || 0} offres collectees`;
    refs.scrapeButton.disabled = true;
    refs.scrapeButton.textContent = "Scrape en cours...";
    refs.clearButton.disabled = true;
  } else {
    refs.scrapeButton.disabled = false;
    refs.scrapeButton.textContent = "Lancer un scrape";
    refs.clearButton.disabled = false;

    if (scrape.error) {
      refs.progressLabel.textContent = "Dernier scrape en erreur";
      refs.progressMeta.textContent = scrape.error;
    } else if (scrape.finished_at_utc) {
      refs.progressLabel.textContent = "Dernier scrape termine";
      refs.progressMeta.textContent = `Termine a ${formatDate(scrape.finished_at_utc)}`;
    } else {
      refs.progressLabel.textContent = "Aucun scrape en cours";
      refs.progressMeta.textContent = "Pret a lancer un scrape complet (toutes pages, tous prix).";
    }
  }

  const runtime = scrape.satellite_runtime || {};
  const satelliteEnabled = Boolean(runtime.enabled);
  const satelliteOk = runtime.ok === true;
  const satelliteWorking = Boolean(scrape.satellite_working) || Boolean(runtime.working);
  const assignedPages = Number(scrape.satellite_assigned_pages || 0);
  const completedPages = Number(scrape.satellite_completed_pages || 0);

  if (!satelliteEnabled) {
    setSatelliteBadge("Desactive", false);
    refs.satelliteStatusText.textContent = "Satellite desactive sur ce noeud.";
  } else if (satelliteOk) {
    setSatelliteBadge("OK", true);
    if (satelliteWorking) {
      refs.satelliteStatusText.textContent = `Le satellite travaille (${completedPages}/${assignedPages} pages).`;
    } else {
      refs.satelliteStatusText.textContent = `Satellite joignable et au repos (${completedPages}/${assignedPages} pages au dernier job).`;
    }
  } else {
    setSatelliteBadge("KO", false);
    const details = runtime.error ? ` (${runtime.error})` : "";
    refs.satelliteStatusText.textContent = `Satellite non joignable${details}`;
  }

  if (scrape.satellite_error) {
    refs.satelliteStatusText.textContent = `Erreur satellite: ${scrape.satellite_error}`;
    setSatelliteBadge("KO", false);
  }

  if (state.previousRunning && !running) {
    if (scrape.error) {
      showToast(`Scrape termine avec erreur: ${scrape.error}`, 3600);
    } else {
      showToast("Scrape termine");
      fetchLatest().catch(() => {});
    }
  }
  state.previousRunning = running;
}

async function fetchLatest({ notifyOnChange = false } = {}) {
  const payload = await requestJSON("/api/latest");
  const changed = payload.updated_at_utc && payload.updated_at_utc !== state.latestStamp;

  state.latestStamp = payload.updated_at_utc || null;
  state.rows = Array.isArray(payload.rows) ? payload.rows : [];
  if (payload.scrape_state) state.scrapeState = payload.scrape_state;

  renderStats();
  renderAllFilters();
  renderOffers();
  renderScrapeState();

  if (changed && notifyOnChange) showToast("Nouveaux resultats detectes");
}

async function fetchScrapeStatus() {
  state.scrapeState = await requestJSON("/api/scrape-status");
  renderScrapeState();
}

async function runScrape() {
  if (state.scrapeState?.running) {
    showToast("Une collecte est deja en cours");
    return;
  }

  refs.scrapeButton.disabled = true;
  refs.scrapeButton.textContent = "Demarrage...";

  resetRowsState();
  renderStats();
  renderAllFilters();
  renderOffers();

  try {
    await requestJSON("/api/scrape", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ all_pages: true, all_prices: true }),
    });
    await fetchScrapeStatus();
    showToast("Scrape lance. Suivi en temps reel actif.");
  } catch (error) {
    showToast(`Erreur: ${error.message}`, 3600);
    refs.scrapeButton.disabled = false;
    refs.scrapeButton.textContent = "Lancer un scrape";
  }
}

async function clearResults() {
  if (state.scrapeState?.running) {
    showToast("Impossible de supprimer pendant un scrape en cours", 3200);
    return;
  }

  refs.clearButton.disabled = true;
  try {
    await requestJSON("/api/clear-results", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });

    resetRowsState();
    renderStats();
    renderAllFilters();
    renderOffers();
    await fetchScrapeStatus();
    showToast("Tous les resultats ont ete supprimes");
  } catch (error) {
    showToast(`Erreur: ${error.message}`, 3600);
  } finally {
    refs.clearButton.disabled = false;
  }
}

function bindFilterSelect(ref, key) {
  ref.addEventListener("change", () => {
    state.filters[key] = ref.value || "all";
    state.currentPage = 1;
    renderOffers();
  });
}

function bindEvents() {
  refs.scrapeButton.addEventListener("click", runScrape);
  refs.clearButton.addEventListener("click", clearResults);

  refs.prevPageButton.addEventListener("click", () => {
    if (state.currentPage <= 1) return;
    state.currentPage -= 1;
    renderOffers();
  });

  refs.nextPageButton.addEventListener("click", () => {
    state.currentPage += 1;
    renderOffers();
  });

  bindFilterSelect(refs.raritySelect, "rarity");
  bindFilterSelect(refs.speedSelect, "speed");
  bindFilterSelect(refs.priceSelect, "price");

  refs.sortPriceText.addEventListener("click", () => cycleSort("price"));
  refs.sortQuantityText.addEventListener("click", () => cycleSort("quantity"));
  refs.sortSpeedText.addEventListener("click", () => cycleSort("speed"));

  refs.refreshButton.addEventListener("click", async () => {
    try {
      await fetchLatest();
      await fetchScrapeStatus();
      showToast("Donnees rafraichies");
    } catch (error) {
      showToast(`Erreur: ${error.message}`, 3200);
    }
  });

  refs.searchInput.addEventListener("input", (event) => {
    state.search = event.target.value || "";
    state.currentPage = 1;
    renderOffers();
  });
}

async function bootstrap() {
  bindEvents();

  try {
    await fetchLatest();
    await fetchScrapeStatus();
  } catch (error) {
    showToast(`Erreur init: ${error.message}`, 3400);
  }

  window.setInterval(() => {
    fetchScrapeStatus().catch(() => {});
  }, 1200);

  window.setInterval(() => {
    fetchLatest({ notifyOnChange: true }).catch(() => {});
  }, 8000);
}

bootstrap();

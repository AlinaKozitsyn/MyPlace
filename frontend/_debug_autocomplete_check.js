
    const form = document.getElementById("compare-form");
    const statusBar = document.getElementById("status-bar");
    const overview = document.getElementById("overview");
    const results = document.getElementById("results");
    const submitButton = document.getElementById("submit-button");
    const childrenAgesField = document.getElementById("children-ages");
    const childrenCountPreview = document.getElementById("children-count-preview");

    const EMPTY_TEXT = "Data not available yet";

    /* ── City autocomplete ── */
    const citySearch = document.getElementById("city-search");
    const cityTags = document.getElementById("city-tags");
    const cityDropdown = document.getElementById("city-dropdown");
    const selectedCities = [];
    let activeOptionIdx = -1;
    let searchTimeout = null;
    let latestSearchToken = 0;
    let currentSuggestions = [];

    function getApiBase() {
      return document.getElementById("api-base").value.trim().replace(/\/+$/, "");
    }

    function escapeHtml(value) {
      return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
    }

    function closeDropdown() {
      currentSuggestions = [];
      activeOptionIdx = -1;
      cityDropdown.classList.remove("open");
      cityDropdown.innerHTML = "";
    }

    function clearPendingCityInput() {
      latestSearchToken += 1;
      citySearch.value = "";
      closeDropdown();
    }

    function isSelectedCity(item) {
      return selectedCities.some((city) => city.id === item.id);
    }

    function renderCityTags() {
      cityTags.querySelectorAll(".city-tag").forEach((el) => el.remove());
      selectedCities.forEach((city, i) => {
        const tag = document.createElement("span");
        tag.className = "city-tag";

        const text = document.createElement("span");
        text.textContent = city.name;

        const button = document.createElement("button");
        button.type = "button";
        button.dataset.idx = String(i);
        button.setAttribute("aria-label", `Remove ${city.name}`);
        button.textContent = "x";

        tag.append(text, button);
        cityTags.insertBefore(tag, citySearch);
      });
    }

    function highlightMatch(name, query) {
      const trimmedQuery = query.trim();
      if (!trimmedQuery) return escapeHtml(name);

      const lowerName = name.toLowerCase();
      const lowerQuery = trimmedQuery.toLowerCase();
      const matchIndex = lowerName.indexOf(lowerQuery);
      if (matchIndex < 0) return escapeHtml(name);

      const before = escapeHtml(name.slice(0, matchIndex));
      const match = escapeHtml(name.slice(matchIndex, matchIndex + trimmedQuery.length));
      const after = escapeHtml(name.slice(matchIndex + trimmedQuery.length));
      return `${before}<mark>${match}</mark>${after}`;
    }

    function setActiveOption(nextIndex) {
      const options = cityDropdown.querySelectorAll(".city-option");
      activeOptionIdx = nextIndex;
      options.forEach((option, index) => {
        option.classList.toggle("active", index === activeOptionIdx);
      });
    }

    function showDropdown(items, query) {
      currentSuggestions = items;
      if (!items.length) {
        closeDropdown();
        return;
      }

      cityDropdown.innerHTML = items
        .map((item, index) => {
          const population = item.population ? Number(item.population).toLocaleString("en-US") : "";
          return `<div class="city-option" data-idx="${index}" data-id="${item.id}">
            <span class="name">${highlightMatch(item.name, query)}</span>
            ${population ? `<span class="pop">${population} residents</span>` : ""}
          </div>`;
        })
        .join("");

      cityDropdown.classList.add("open");
      setActiveOption(-1);
    }

    function selectCity(item) {
      if (!item || isSelectedCity(item)) {
        clearPendingCityInput();
        citySearch.focus();
        return;
      }

      selectedCities.push({
        id: item.id,
        name: item.name
      });
      renderCityTags();
      clearPendingCityInput();
      citySearch.focus();
    }

    cityTags.addEventListener("click", (e) => {
      if (e.target.tagName === "BUTTON" && e.target.dataset.idx !== undefined) {
        selectedCities.splice(Number(e.target.dataset.idx), 1);
        renderCityTags();
      }
      citySearch.focus();
    });

    cityDropdown.addEventListener("click", (e) => {
      const option = e.target.closest(".city-option");
      if (!option) return;

      const selected = currentSuggestions[Number(option.dataset.idx)];
      selectCity(selected);
    });

    citySearch.addEventListener("input", () => {
      clearTimeout(searchTimeout);
      const query = citySearch.value.trim();

      if (!query) {
        latestSearchToken += 1;
        closeDropdown();
        return;
      }

      const searchToken = ++latestSearchToken;
      searchTimeout = setTimeout(async () => {
        try {
          const res = await fetch(`${getApiBase()}/settlements/search?q=${encodeURIComponent(query)}&limit=15`);
          if (!res.ok || searchToken !== latestSearchToken) return;

          const data = await res.json();
          if (searchToken !== latestSearchToken) return;

          const filtered = data.filter((item) => !isSelectedCity(item));
          showDropdown(filtered, query);
        } catch (_) {
          if (searchToken === latestSearchToken) {
            closeDropdown();
          }
        }
      }, 200);
    });

    citySearch.addEventListener("keydown", (e) => {
      const hasOptions = currentSuggestions.length > 0;

      if (e.key === "ArrowDown") {
        if (!hasOptions) return;
        e.preventDefault();
        setActiveOption(Math.min(activeOptionIdx + 1, currentSuggestions.length - 1));
      } else if (e.key === "ArrowUp") {
        if (!hasOptions) return;
        e.preventDefault();
        setActiveOption(Math.max(activeOptionIdx - 1, 0));
      } else if (e.key === "Enter") {
        e.preventDefault();
        if (activeOptionIdx >= 0 && currentSuggestions[activeOptionIdx]) {
          selectCity(currentSuggestions[activeOptionIdx]);
        } else {
          clearPendingCityInput();
        }
      } else if (e.key === "Escape") {
        clearPendingCityInput();
      } else if (e.key === "Backspace" && !citySearch.value && selectedCities.length) {
        selectedCities.pop();
        renderCityTags();
      }
    });

    citySearch.addEventListener("blur", () => {
      window.setTimeout(() => {
        if (!document.activeElement.closest("#city-picker")) {
          clearPendingCityInput();
        }
      }, 120);
    });

    document.addEventListener("click", (e) => {
      if (!e.target.closest("#city-picker")) {
        clearPendingCityInput();
      }
    });

    function parseChildren() {
      return childrenAgesField.value
        .split(/[,\n]/)
        .map((item) => item.trim())
        .filter(Boolean)
        .map((age) => ({ age: Number(age) }))
        .filter((child) => Number.isFinite(child.age) && child.age >= 0);
    }

    function updateChildrenPreview() {
      childrenCountPreview.value = String(parseChildren().length);
    }

    function formatValue(value, suffix = "") {
      if (value === null || value === undefined || value === "") {
        return EMPTY_TEXT;
      }

      if (typeof value === "number") {
        return `${value.toLocaleString("en-US")}${suffix}`;
      }

      return `${value}${suffix}`;
    }

    function formatCurrency(value) {
      if (value === null || value === undefined) {
        return EMPTY_TEXT;
      }

      return `${Number(value).toLocaleString("en-US", {
        minimumFractionDigits: 0,
        maximumFractionDigits: 2
      })} ILS`;
    }

    function formatPercent(value) {
      if (value === null || value === undefined) {
        return EMPTY_TEXT;
      }

      return `${(Number(value) * 100).toLocaleString("en-US", {
        minimumFractionDigits: 0,
        maximumFractionDigits: 1
      })}%`;
    }

    function metricRow(label, value) {
      return `
        <div class="metric-row">
          <span class="metric-label">${label}</span>
          <span class="metric-value">${value}</span>
        </div>
      `;
    }

    function renderRank(rankData) {
      if (!rankData) {
        return EMPTY_TEXT;
      }

      return rankData.summary || `${formatValue(rankData.display_place)} / ${formatValue(rankData.out_of)}`;
    }

    function renderCommuteCard(title, commute) {
      if (!commute) {
        return `
          <div class="section-card">
            <div class="section-title">${title}</div>
            <div class="metric-list">
              ${metricRow("Status", EMPTY_TEXT)}
            </div>
          </div>
        `;
      }

      return `
        <div class="section-card">
          <div class="section-title">${title}</div>
          <div class="metric-list">
            ${metricRow("Status", formatValue(commute.status))}
            ${metricRow("Mode", formatValue(commute.mode))}
            ${metricRow("Duration", formatValue(commute.duration_min, " min"))}
            ${metricRow("Distance", formatValue(commute.distance_km, " km"))}
            ${metricRow("Monthly cost", formatCurrency(commute.monthly_cost))}
          </div>
        </div>
      `;
    }

    function renderCityCard(cityResult) {
      const quality = cityResult.quality_of_life || {};
      const taxes = cityResult.taxes || {};
      const safety = cityResult.safety || {};
      const costs = cityResult.costs || {};
      const education = cityResult.education || {};
      const summary = cityResult.summary || {};
      const completeness = cityResult.data_completeness || {};

      return `
        <article class="panel city-card">
          <header class="city-header">
            <div>
              <h2>${cityResult.city}</h2>
              <div class="hint">Completion: ${formatValue(completeness.completion_percent, "%")}</div>
            </div>
            <span class="badge">${formatValue(completeness.ready_fields)} ready / ${formatValue(completeness.missing_fields)} missing</span>
          </header>

          <section class="section-grid">
            ${renderCommuteCard("Parent 1 commute", cityResult.transport?.parent1_work_commute)}
            ${renderCommuteCard("Parent 2 commute", cityResult.transport?.parent2_work_commute)}

            <div class="section-card">
              <div class="section-title">Monthly costs</div>
              <div class="metric-list">
                ${metricRow("Commute", formatCurrency(costs.commute_monthly))}
                ${metricRow("Rent", formatCurrency(costs.rent_monthly))}
                ${metricRow("Arnona", formatCurrency(costs.arnona_monthly))}
                ${metricRow("Education", formatCurrency(costs.education_monthly))}
                ${metricRow("Total", formatCurrency(costs.total_monthly))}
              </div>
            </div>

            <div class="section-card">
              <div class="section-title">Taxes</div>
              <div class="metric-list">
                ${metricRow("Family income", formatCurrency(taxes.total_family_income_monthly))}
                ${metricRow("Tax ceiling", formatCurrency(taxes.tax_ceiling_annual))}
                ${metricRow("Benefit percent", formatPercent(taxes.tax_benefit_percent))}
                ${metricRow("Annual benefit", formatCurrency(taxes.tax_benefit_annual))}
                ${metricRow("Monthly benefit", formatCurrency(taxes.tax_benefit_monthly))}
              </div>
            </div>

            <div class="section-card">
              <div class="section-title">Quality of life</div>
              <div class="metric-list">
                ${metricRow("Potential accessibility", renderRank(quality.potential_accessibility_rank))}
                ${metricRow("Peripherality", renderRank(quality.peripherality_rank_2020))}
                ${metricRow("Social-economic", renderRank(quality.social_economic_cluster_2021))}
                ${metricRow("Cars per household", formatValue(quality.average_cars_per_household))}
                ${metricRow("Religion", formatValue(quality.religion))}
                ${metricRow("Median age", formatValue(quality.age_median))}
              </div>
            </div>

            <div class="section-card">
              <div class="section-title">Education</div>
              <div class="metric-list">
                ${metricRow("Schools total", formatValue(education.schools_total))}
                ${metricRow("Elementary", formatValue(education.schools_elementary))}
                ${metricRow("Middle schools", formatValue(education.schools_middle_schools))}
                ${metricRow("High schools", formatValue(education.schools_high_schools))}
                ${metricRow("Dropout rate", formatValue(education.dropout_rate_total, "%"))}
                ${metricRow("Bagrut eligibility", formatValue(education.bagrut_eligibility_rate, "%"))}
              </div>
            </div>

            <div class="section-card">
              <div class="section-title">Safety</div>
              <div class="metric-list">
                ${metricRow("Crime index", formatValue(safety.crime_index))}
                ${metricRow("Cluster 1 / 1000", formatValue(safety.cluster_1_per_1000))}
                ${metricRow("Cluster 2 / 1000", formatValue(safety.cluster_2_per_1000))}
                ${metricRow("Cluster 3 / 1000", formatValue(safety.cluster_3_per_1000))}
              </div>
            </div>

            <div class="section-card full">
              <div class="section-title">Highlights and warnings</div>
              <div class="pill-list">
                ${(summary.highlights || []).length
                  ? summary.highlights.map((item) => `<span class="pill">${item}</span>`).join("")
                  : `<span class="pill">${EMPTY_TEXT}</span>`}
              </div>
              <div class="warning-list" style="margin-top: 10px;">
                ${(summary.warnings || []).length
                  ? summary.warnings.map((item) => `<span class="warning">${item}</span>`).join("")
                  : `<span class="warning">No warnings</span>`}
              </div>
            </div>

            <div class="section-card full">
              <div class="section-title">Missing categories</div>
              <div class="pill-list">
                ${(completeness.missing_categories || []).length
                  ? completeness.missing_categories.map((item) => `<span class="warning">${item}</span>`).join("")
                  : `<span class="pill">All tracked categories available</span>`}
              </div>
            </div>
          </section>
        </article>
      `;
    }

    function showStatus(message, tone = "info") {
      statusBar.textContent = message;
      statusBar.className = `panel status-bar visible ${tone}`;
    }

    function hideStatus() {
      statusBar.textContent = "";
      statusBar.className = "panel status-bar info";
    }

    function renderOverview(data) {
      overview.className = "panel overview visible";
      overview.innerHTML = `
        <div>
          <div class="eyebrow">Request summary</div>
          <h2 class="group-title" style="margin-top: 6px;">${data.meta.comparison_type} generated at <span class="mono">${data.meta.generated_at}</span></h2>
        </div>
        <div class="overview-grid">
          <div class="overview-card">
            <span class="hint">Cities</span>
            <strong>${data.input_summary.cities.join(" | ")}</strong>
          </div>
          <div class="overview-card">
            <span class="hint">Children</span>
            <strong>${formatValue(data.input_summary.family.children_count)}</strong>
          </div>
          <div class="overview-card">
            <span class="hint">Desired rooms</span>
            <strong>${formatValue(data.input_summary.family.desired_rooms)}</strong>
          </div>
          <div class="overview-card">
            <span class="hint">Family income</span>
            <strong>${formatCurrency(
              (data.input_summary.family.parent1_income || 0) + (data.input_summary.family.parent2_income || 0)
            )}</strong>
          </div>
        </div>
      `;
    }

    function buildPayload() {
      const formData = new FormData(form);
      const children = parseChildren();
      const cities = selectedCities.map((city) => city.name);

      const parent2Address = (formData.get("parent2Address") || "").toString().trim();

      const payload = {
        cities,
        family: {
          parent1_income: Number(formData.get("parent1Income")) || 0,
          parent2_income: Number(formData.get("parent2Income")) || 0,
          desired_rooms: Number(formData.get("desiredRooms")) || null,
          children
        },
        parent1: {
          work_address: (formData.get("parent1Address") || "").toString().trim(),
          commute_mode: formData.get("parent1Mode"),
          departure_time: formData.get("parent1Time") || null,
          work_days_per_week: Number(formData.get("parent1Days")) || 5
        },
        departure_date: formData.get("departureDate") || null
      };

      if (parent2Address) {
        payload.parent2 = {
          work_address: parent2Address,
          commute_mode: formData.get("parent2Mode"),
          departure_time: formData.get("parent2Time") || null,
          work_days_per_week: Number(formData.get("parent2Days")) || 5
        };
      }

      return payload;
    }

    async function handleSubmit(event) {
      event.preventDefault();
      hideStatus();
      overview.className = "panel overview";
      overview.innerHTML = "";
      results.innerHTML = "";

      const apiBase = document.getElementById("api-base").value.trim().replace(/\/+$/, "");
      const payload = buildPayload();

      if (!payload.cities.length) {
        showStatus("Add at least one city before comparing.", "error");
        return;
      }

      if (!payload.parent1.work_address) {
        showStatus("Parent 1 work address is required.", "error");
        return;
      }

      submitButton.disabled = true;
      showStatus("Sending comparison request...", "info");

      try {
        const response = await fetch(`${apiBase}/compare`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json"
          },
          body: JSON.stringify(payload)
        });

        const rawText = await response.text();
        let data = null;

        try {
          data = rawText ? JSON.parse(rawText) : null;
        } catch (parseError) {
          throw new Error(`Server returned non-JSON output:\n${rawText}`);
        }

        if (!response.ok) {
          const detail = data?.detail ? JSON.stringify(data.detail, null, 2) : rawText;
          throw new Error(`Request failed with status ${response.status}.\n${detail}`);
        }

        renderOverview(data);
        results.innerHTML = (data.results || []).map(renderCityCard).join("");
        showStatus("Comparison completed.", "info");
      } catch (error) {
        const message = error.message === "Failed to fetch"
          ? "Failed to fetch. Check that the FastAPI server is running on the API base URL and restart it after enabling CORS."
          : (error.message || "Request failed.");
        showStatus(message, "error");
      } finally {
        submitButton.disabled = false;
      }
    }

    childrenAgesField.addEventListener("input", updateChildrenPreview);
    form.addEventListener("submit", handleSubmit);
    updateChildrenPreview();
  
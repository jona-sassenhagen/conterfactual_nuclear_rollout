const DATA_URL =
  window.DATA_URL || new URL("data/scenario_data.json", document.baseURI).toString();

const formatNumber = (value, decimals = 0) => {
  return Number(value || 0).toLocaleString(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
};

const formatGW = (gw) => `${formatNumber(gw, 1)} GW`;
const formatGWPrecise = (gw, decimals = 2) => `${formatNumber(gw, decimals)} GW`;
const formatMt = (mt) => `${formatNumber(mt, 1)} Mt`;
const formatTWh = (twh) => `${formatNumber(twh, 0)} TWh`;

const DONUT_SOURCES = [
  { id: 'nuclear', color: 'var(--mix-nuclear)' },
  { id: 'renewables', color: 'var(--mix-renewables)' },
  { id: 'fossil', color: 'var(--mix-fossil)' },
];

class DonutChart {
  constructor(root, options = {}) {
    this.root = root;
    this.svg = root ? root.querySelector('svg') : null;
    this.totalLabel = root ? root.querySelector('[data-role="total"]') : null;
    this.yearLabel = root ? root.querySelector('[data-role="year"]') : null;
    this.legendValues = {};
    this.categories = (options.categories || DONUT_SOURCES).map((entry) => ({ ...entry }));
    if (!this.svg) {
      return;
    }

    const legendItems = root.querySelectorAll('.mix-legend li');
    legendItems.forEach((item) => {
      const key = item.getAttribute('data-source');
      const valueEl = item.querySelector('.value');
      if (key && valueEl) {
        this.legendValues[key] = valueEl;
      }
    });

    this.size = options.size || 160;
    this.center = this.size / 2;
    this.radius = options.radius || 60;
    this.strokeWidth = options.strokeWidth || 18;
    this.circumference = 2 * Math.PI * this.radius;

    this.svg.setAttribute('viewBox', `0 0 ${this.size} ${this.size}`);
    this.svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');

    this.background = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    this.background.setAttribute('cx', this.center);
    this.background.setAttribute('cy', this.center);
    this.background.setAttribute('r', this.radius);
    this.background.setAttribute('fill', 'none');
    this.background.setAttribute('stroke', 'rgba(255, 255, 255, 0.12)');
    this.background.setAttribute('stroke-width', this.strokeWidth);
    this.background.setAttribute('transform', `rotate(-90 ${this.center} ${this.center})`);
    this.svg.appendChild(this.background);

    this.segments = this.categories.map((category) => {
      const segment = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      segment.setAttribute('cx', this.center);
      segment.setAttribute('cy', this.center);
      segment.setAttribute('r', this.radius);
      segment.setAttribute('fill', 'none');
      segment.setAttribute('stroke', category.color || '#ffffff');
      segment.setAttribute('stroke-width', this.strokeWidth);
      segment.setAttribute('stroke-linecap', 'round');
      segment.setAttribute('transform', `rotate(-90 ${this.center} ${this.center})`);
      segment.style.strokeDasharray = `0 ${this.circumference}`;
      segment.style.strokeDashoffset = '0';
      this.svg.appendChild(segment);
      return { id: category.id, node: segment };
    });
  }

  update(values = {}, year) {
    if (!this.svg) {
      return;
    }
    const totalsById = {};
    let total = 0;
    this.categories.forEach((category) => {
      const raw = Number(values[category.id] || 0);
      const safe = Number.isFinite(raw) && raw > 0 ? raw : 0;
      totalsById[category.id] = safe;
      total += safe;
    });

    let offset = 0;
    this.segments.forEach((segment) => {
      const value = totalsById[segment.id] || 0;
      const length = total > 0 ? (value / total) * this.circumference : 0;
      segment.node.style.strokeDasharray = `${length} ${this.circumference}`;
      segment.node.style.strokeDashoffset = `${-offset}`;
      segment.node.style.opacity = total > 0 && value > 0 ? '1' : '0';
      offset += length;
    });

    if (this.totalLabel) {
      const precision = total === 0 ? 0 : (total >= 100 ? 0 : 1);
      this.totalLabel.textContent = formatNumber(total, precision);
    }
    if (this.yearLabel && typeof year === 'number') {
      this.yearLabel.textContent = year;
    }

    Object.entries(this.legendValues).forEach(([key, node]) => {
      const value = totalsById[key] || 0;
      const decimals = value === 0 ? 0 : (value >= 100 ? 0 : 1);
      node.textContent = `${formatNumber(value, decimals)} TWh`;
      const parent = node.closest('li');
      if (parent) {
        parent.style.opacity = value > 0 ? '1' : '0.25';
      }
    });
  }
}

class LineChart {
  constructor(svg, years, primaryValues, options = {}) {
    this.svg = svg;
    this.years = years;
    this.primaryValues = primaryValues;
    this.secondaryValues = options.secondaryValues || null;
    this.axisFormatter = options.axisFormatter || ((v) => `${formatNumber(v, 0)}`);
    this.width = 360;
    this.height = 180;
    this.margin = { top: 16, right: 18, bottom: 30, left: 48 };
    this.svg.setAttribute("viewBox", `0 0 ${this.width} ${this.height}`);
    this.svg.setAttribute("preserveAspectRatio", "xMidYMid meet");

    this.innerWidth = this.width - this.margin.left - this.margin.right;
    this.innerHeight = this.height - this.margin.top - this.margin.bottom;

    this.maxValue = this.computeMaxValue();
    this.pointsPrimary = this.computePoints(this.primaryValues);
    this.pointsSecondary = this.secondaryValues
      ? this.computePoints(this.secondaryValues)
      : null;

    this.drawGrid();
    this.drawAxes();
    this.createPaths();
    this.currentIndex = 0;
    this.update(0);
  }

  computeMaxValue() {
    const series = [this.primaryValues];
    if (this.secondaryValues) {
      series.push(this.secondaryValues);
    }
    const maxCandidate = Math.max(
      1,
      ...series.flat().map((v) => Number.isFinite(v) ? v : 0)
    );
    return maxCandidate;
  }

  computePoints(values) {
    const points = [];
    const n = Math.max(1, this.years.length - 1);
    for (let i = 0; i < values.length; i += 1) {
      const ratio = i / n;
      const x = this.margin.left + ratio * this.innerWidth;
      const clamped = Math.max(0, values[i]);
      const yRatio = this.maxValue > 0 ? clamped / this.maxValue : 0;
      const y = this.margin.top + (1 - yRatio) * this.innerHeight;
      points.push([x, y]);
    }
    return points;
  }

  drawGrid() {
    const gridGroup = document.createElementNS("http://www.w3.org/2000/svg", "g");
    const lines = 4;
    for (let i = 0; i <= lines; i += 1) {
      const ratio = i / lines;
      const y = this.margin.top + ratio * this.innerHeight;
      const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
      line.setAttribute("x1", this.margin.left);
      line.setAttribute("x2", this.margin.left + this.innerWidth);
      line.setAttribute("y1", y);
      line.setAttribute("y2", y);
      line.setAttribute("class", "chart-grid");
      gridGroup.appendChild(line);
    }
    this.svg.appendChild(gridGroup);
  }

  drawAxes() {
    const axisGroup = document.createElementNS("http://www.w3.org/2000/svg", "g");
    const yZero = this.margin.top + this.innerHeight;
    const xStart = this.margin.left;
    const xEnd = this.margin.left + this.innerWidth;

    const xAxis = document.createElementNS("http://www.w3.org/2000/svg", "line");
    xAxis.setAttribute("x1", xStart);
    xAxis.setAttribute("x2", xEnd);
    xAxis.setAttribute("y1", yZero);
    xAxis.setAttribute("y2", yZero);
    xAxis.setAttribute("class", "chart-grid");
    axisGroup.appendChild(xAxis);

    const startLabel = document.createElementNS("http://www.w3.org/2000/svg", "text");
    startLabel.setAttribute("x", xStart);
    startLabel.setAttribute("y", this.height - 6);
    startLabel.setAttribute("class", "chart-axis-label");
    startLabel.textContent = this.years[0];
    axisGroup.appendChild(startLabel);

    const endLabel = document.createElementNS("http://www.w3.org/2000/svg", "text");
    endLabel.setAttribute("x", xEnd - 24);
    endLabel.setAttribute("y", this.height - 6);
    endLabel.setAttribute("class", "chart-axis-label");
    endLabel.textContent = this.years[this.years.length - 1];
    axisGroup.appendChild(endLabel);

    const maxLabel = document.createElementNS("http://www.w3.org/2000/svg", "text");
    maxLabel.setAttribute("x", 8);
    maxLabel.setAttribute("y", this.margin.top + 4);
    maxLabel.setAttribute("class", "chart-axis-label");
    maxLabel.textContent = this.axisFormatter(this.maxValue);
    axisGroup.appendChild(maxLabel);

    const minLabel = document.createElementNS("http://www.w3.org/2000/svg", "text");
    minLabel.setAttribute("x", 8);
    minLabel.setAttribute("y", this.margin.top + this.innerHeight);
    minLabel.setAttribute("class", "chart-axis-label");
    minLabel.textContent = this.axisFormatter(0);
    axisGroup.appendChild(minLabel);

    this.maxAxisLabel = maxLabel;
    this.minAxisLabel = minLabel;
    this.svg.appendChild(axisGroup);
  }

  createPaths() {
    this.pathPrimary = document.createElementNS("http://www.w3.org/2000/svg", "path");
    this.pathPrimary.setAttribute("class", "chart-line primary");
    this.svg.appendChild(this.pathPrimary);

    this.pathSecondary = null;

    this.cursorPrimary = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    this.cursorPrimary.setAttribute("r", 4);
    this.cursorPrimary.setAttribute("class", "chart-marker primary");
    this.svg.appendChild(this.cursorPrimary);
    this.verticalLine = document.createElementNS("http://www.w3.org/2000/svg", "line");
    this.verticalLine.setAttribute("class", "chart-vertical");
    this.svg.appendChild(this.verticalLine);
  }

  buildPath(points, lastIndex) {
    const slice = points.slice(0, lastIndex + 1);
    if (slice.length === 0) {
      return "";
    }
    if (slice.length === 1) {
      const [x, y] = slice[0];
      return `M${x} ${y}`;
    }
    return slice
      .map(([x, y], idx) => `${idx === 0 ? "M" : "L"}${x.toFixed(2)} ${y.toFixed(2)}`)
      .join(" ");
  }

  update(index) {
    const clamped = Math.min(Math.max(index, 0), this.years.length - 1);
    this.currentIndex = clamped;
    this.pathPrimary.setAttribute("d", this.buildPath(this.pointsPrimary, clamped));
    const primaryPoint = this.pointsPrimary[clamped];
    if (primaryPoint) {
      this.cursorPrimary.setAttribute("cx", primaryPoint[0]);
      this.cursorPrimary.setAttribute("cy", primaryPoint[1]);
      this.verticalLine.setAttribute("x1", primaryPoint[0]);
      this.verticalLine.setAttribute("x2", primaryPoint[0]);
      this.verticalLine.setAttribute("y1", this.margin.top);
      this.verticalLine.setAttribute("y2", this.margin.top + this.innerHeight);
    }

    if (this.secondaryValues && this.pathSecondary && this.pointsSecondary) {
      this.pathSecondary.setAttribute(
        "d",
        this.buildPath(this.pointsSecondary, clamped)
      );
    }
  }

  setDomainMax(maxValue) {
    const sanitized = Math.max(1, Number(maxValue || 0));
    if (!Number.isFinite(sanitized)) {
      return;
    }
    if (Math.abs(sanitized - this.maxValue) < 1e-6) {
      return;
    }
    this.maxValue = sanitized;
    this.pointsPrimary = this.computePoints(this.primaryValues);
    if (this.secondaryValues) {
      this.pointsSecondary = this.computePoints(this.secondaryValues);
    }
    if (this.maxAxisLabel) {
      this.maxAxisLabel.textContent = this.axisFormatter(this.maxValue);
    }
    this.update(this.currentIndex ?? 0);
  }

  setSecondary(values) {
    if (!Array.isArray(values) || values.length !== this.years.length) {
      this.secondaryValues = null;
      this.pointsSecondary = null;
      if (this.pathSecondary) {
        this.pathSecondary.remove();
        this.pathSecondary = null;
      }
      this.update(this.currentIndex ?? 0);
      return;
    }

    this.secondaryValues = values.map((value) => (Number.isFinite(value) ? Number(value) : 0));
    this.pointsSecondary = this.computePoints(this.secondaryValues);

    if (!this.pathSecondary) {
      this.pathSecondary = document.createElementNS("http://www.w3.org/2000/svg", "path");
      this.pathSecondary.setAttribute("class", "chart-line secondary");
      this.svg.insertBefore(this.pathSecondary, this.cursorPrimary);
    }

    this.update(this.currentIndex ?? 0);
  }
}

const indexByYear = (records = []) => {
  const map = new Map();
  records.forEach((entry) => {
    if (typeof entry.year === "number") {
      map.set(entry.year, entry);
    }
  });
  return map;
};

const buildSeries = (years, map, accessor) => {
  let lastValue = 0;
  return years.map((year) => {
    const record = map.get(year);
    if (record) {
      const value = accessor(record);
      if (Number.isFinite(value)) {
        lastValue = value;
      }
    }
    return lastValue;
  });
};

class ScenarioView {
  constructor(root, data, years, options = {}) {
    this.root = root;
    this.data = data;
    this.years = years;
    this.options = options;
    this.baselines = options.baselines || { site: {}, municipality: {} };
    this.stats = {
      co2: root.querySelector(".stat-co2"),
      clean: root.querySelector(".stat-clean"),
      nuclear: root.querySelector(".stat-nuclear"),
      fossil: root.querySelector(".stat-fossil"),
    };
    this.tallyElements = {
      nuclear: {
        opened: root.querySelector('.tallies [data-tally="nuclear"] [data-role="opened"]'),
        closed: root.querySelector('.tallies [data-tally="nuclear"] [data-role="closed"]'),
      },
      fossil: {
        opened: root.querySelector('.tallies [data-tally="fossil"] [data-role="opened"]'),
        closed: root.querySelector('.tallies [data-tally="fossil"] [data-role="closed"]'),
      },
    };
    this.eventLists = {
      construction: root.querySelector('.event-column[data-kind="construction"] .event-list'),
      closure: root.querySelector('.event-column[data-kind="closure"] .event-list'),
    };

    this.capacityMap = indexByYear(data.capacity_timeseries);
    this.emissionsMap = indexByYear(data.emissions);
    this.eventsByYear = new Map();
    years.forEach((year) => this.eventsByYear.set(year, []));
    (data.events || []).forEach((event) => {
      const year = typeof event.year === "number" ? event.year : parseInt((event.date || "").slice(0, 4), 10);
      if (this.eventsByYear.has(year)) {
        this.eventsByYear.get(year).push(event);
      }
    });
    this.eventsByYear.forEach((list, year) => {
      list.sort((a, b) => (a.date || "").localeCompare(b.date || ""));
    });

    this.sortedEvents = (data.events || [])
      .map((event) => ({ ...event }))
      .sort((a, b) => {
        const dateA = (a.date || `${a.year}-12-31`);
        const dateB = (b.date || `${b.year}-12-31`);
        if (dateA === dateB) {
          return (a.site || a.name || "").localeCompare(b.site || b.name || "");
        }
        return dateA.localeCompare(dateB);
      });

    this.eventBubbles = {
      construction: new Map(),
      closure: new Map(),
    };
    this.lastTimelineYear = null;

    this.cumulativeCounts = this.buildCumulativeCounts(years);

    this.series = {
      co2: buildSeries(years, this.emissionsMap, (record) => Number(record.co2_mt || 0)),
      clean: buildSeries(years, this.emissionsMap, (record) => Number(record.clean_twh || 0)),
      nuclear: buildSeries(years, this.capacityMap, (record) => Number(record.nuclear_mw || 0) / 1000),
      fossil: buildSeries(years, this.capacityMap, (record) => Number(record.fossil_mw || 0) / 1000),
    };

    this.charts = {
      co2: new LineChart(
        root.querySelector('[data-chart="co2"] svg'),
        years,
        this.series.co2,
        { axisFormatter: (value) => `${formatNumber(value, 0)} Mt` }
      ),
      clean: new LineChart(
        root.querySelector('[data-chart="clean"] svg'),
        years,
        this.series.clean,
        { axisFormatter: (value) => `${formatNumber(value, 0)} TWh` }
      ),
    };

    const donutRoot = root.querySelector('[data-donut]');
    this.mixChart = donutRoot ? new DonutChart(donutRoot) : null;
  }

  setComparisonSeries(series = {}) {
    this.comparisonSeries = series;
    if (this.charts && this.charts.co2) {
      this.charts.co2.setSecondary(Array.isArray(series.co2) ? series.co2 : null);
    }
    if (this.charts && this.charts.clean) {
      this.charts.clean.setSecondary(Array.isArray(series.clean) ? series.clean : null);
    }
  }

  update(index) {
    const clamped = Math.min(Math.max(index, 0), this.years.length - 1);
    this.charts.co2.update(clamped);
    this.charts.clean.update(clamped);

    const co2Value = this.series.co2[clamped];
    const cleanValue = this.series.clean[clamped];
    const nuclearGW = this.series.nuclear[clamped];
    const fossilGW = this.series.fossil[clamped];

    if (this.stats.co2) {
      this.stats.co2.textContent = formatMt(co2Value);
    }
    if (this.stats.clean) {
      this.stats.clean.textContent = formatTWh(cleanValue);
    }
    if (this.stats.nuclear) {
      this.stats.nuclear.textContent = formatGW(nuclearGW);
    }
    if (this.stats.fossil) {
      this.stats.fossil.textContent = formatGW(fossilGW);
    }

    const currentYear = this.years[clamped];
    if (this.mixChart) {
      const record = this.emissionsMap.get(currentYear) || {};
      const nuclearTwh = Number(record.nuclear_twh || 0);
      const renewablesTwh = Number(record.renewables_twh || 0);
      const fossilTwh = Number(record.fossil_twh || 0);
      const totalCandidate = Number(record.total_twh || 0);
      const fallbackTotal = nuclearTwh + renewablesTwh + fossilTwh;
      const totalTwh = Number.isFinite(totalCandidate) && totalCandidate > 0
        ? totalCandidate
        : fallbackTotal;
      const otherTwhRaw = totalTwh - (nuclearTwh + renewablesTwh + fossilTwh);
      const otherTwh = otherTwhRaw > 0 ? otherTwhRaw : 0;
      const fossilWithResidual = fossilTwh + otherTwh;
      this.mixChart.update({
        nuclear: nuclearTwh,
        renewables: renewablesTwh,
        fossil: fossilWithResidual,
      }, currentYear);
    }
    if (this.lastTimelineYear !== null && currentYear < this.lastTimelineYear) {
      this.resetEventColumns();
    }

    this.updateTallies(currentYear);
    this.updateEventColumns(currentYear);
    this.lastTimelineYear = currentYear;
  }

  eventTypeToCategory(type = "") {
    switch (type) {
      case "nuclear_build":
        return "nuclear_opened";
      case "nuclear_closure":
        return "nuclear_closed";
      case "fossil_build":
        return "fossil_opened";
      case "fossil_closure":
        return "fossil_closed";
      default:
        return null;
    }
  }

  buildCumulativeCounts(years) {
    const totals = {
      nuclear_opened: 0,
      nuclear_closed: 0,
      fossil_opened: 0,
      fossil_closed: 0,
    };
    const cumulative = new Map();
    years.forEach((year) => {
      const events = this.eventsByYear.get(year) || [];
      events.forEach((event) => {
        const category = this.eventTypeToCategory(event.event_type);
        if (category) {
          totals[category] += 1;
        }
      });
      cumulative.set(year, { ...totals });
    });
    return cumulative;
  }

  updateTallies(year) {
    const totals = this.cumulativeCounts.get(year) || {
      nuclear_opened: 0,
      nuclear_closed: 0,
      fossil_opened: 0,
      fossil_closed: 0,
    };
    const nuclear = this.tallyElements.nuclear;
    if (nuclear) {
      if (nuclear.opened) {
        nuclear.opened.textContent = formatNumber(totals.nuclear_opened || 0, 0);
      }
      if (nuclear.closed) {
        nuclear.closed.textContent = formatNumber(totals.nuclear_closed || 0, 0);
      }
    }
    const fossil = this.tallyElements.fossil;
    if (fossil) {
      if (fossil.opened) {
        fossil.opened.textContent = formatNumber(totals.fossil_opened || 0, 0);
      }
      if (fossil.closed) {
        fossil.closed.textContent = formatNumber(totals.fossil_closed || 0, 0);
      }
    }
  }

  aggregateEventsUpTo(year) {
    const aggregates = {
      construction: new Map(),
      closure: new Map(),
    };
    const summary = new Map();
    const yearChanges = {
      construction: new Map(),
      closure: new Map(),
    };
    const latestByKind = {
      construction: new Map(),
      closure: new Map(),
    };

    const ensureSummary = (summaryKey, bucket) => {
      if (!summary.has(summaryKey)) {
        summary.set(summaryKey, new Map());
      }
      const siteSummary = summary.get(summaryKey);
      if (!siteSummary.has(bucket)) {
        siteSummary.set(bucket, {
          openedCount: 0,
          openedMw: 0,
          closedCount: 0,
          closedMw: 0,
          seeded: false,
        });
      }
      return siteSummary.get(bucket);
    };

    const baselines = this.baselines || {};
    const municipalityBaselines = baselines.municipality || {};
    Object.entries(municipalityBaselines).forEach(([bucket, mapping]) => {
      Object.entries(mapping || {}).forEach(([municipality, stats]) => {
        const record = ensureSummary(municipality, bucket);
        record.openedCount += Number(stats.count || 0);
        record.openedMw += Number(stats.capacity_mw || 0);
        record.seeded = true;
      });
    });

    this.sortedEvents.forEach((event) => {
      if (typeof event.year !== 'number' || event.year > year) {
        return;
      }
      const classification = this.classifyEvent(event);
      if (!classification) {
        return;
      }

      const {
        kind,
        bucket,
        deltaCount,
        deltaMw,
        namedMw = deltaMw,
        dummyMw = 0,
      } = classification;
      const municipality = (typeof event.municipality === 'string' && event.municipality.trim())
        ? event.municipality.trim()
        : '';
      const siteName = event.site || event.name || 'Unknown site';
      let derivedMunicipality = municipality;
      if (!derivedMunicipality && /\(.+\)/.test(siteName)) {
        const match = siteName.match(/\(([^)]+)\)\s*$/);
        if (match) {
          derivedMunicipality = match[1].trim();
        }
      }
      const summaryKey = derivedMunicipality || siteName || 'Unknown site';
      const displayName = summaryKey;

      const summaryStats = ensureSummary(summaryKey, bucket);
      if (kind === 'construction') {
        summaryStats.openedCount += deltaCount;
        summaryStats.openedMw += namedMw;
      } else {
        if (!summaryStats.seeded && summaryStats.openedCount === 0 && summaryStats.closedCount === 0) {
          summaryStats.openedCount += deltaCount;
          summaryStats.openedMw += namedMw;
          summaryStats.seeded = true;
        }
        summaryStats.closedCount += deltaCount;
        summaryStats.closedMw += namedMw;
      }

      const latest = latestByKind[kind].get(summaryKey) || {
        siteLabel: displayName,
        municipality: derivedMunicipality,
        lastYear: event.year,
        lastDate: event.date || `${event.year}-12-31`,
        lastBucket: bucket,
        lastEntries: {},
      };
      latest.lastYear = event.year;
      latest.lastDate = event.date || `${event.year}-12-31`;
      latest.lastBucket = bucket;
      latest.municipality = derivedMunicipality;
      latest.siteLabel = displayName;
      latest.lastEntries = {
        [bucket]: {
          openedCount: kind === 'construction' ? deltaCount : 0,
          openedMw: kind === 'construction' ? namedMw : 0,
          closedCount: kind === 'closure' ? deltaCount : 0,
          closedMw: kind === 'closure' ? namedMw : 0,
          dummyClosedMw: kind === 'closure' ? dummyMw : 0,
        },
      };
      latestByKind[kind].set(summaryKey, latest);

      if (event.year === year) {
        if (!yearChanges[kind].has(summaryKey)) {
          yearChanges[kind].set(summaryKey, new Map());
        }
        const changeMap = yearChanges[kind].get(summaryKey);
        const changeInfo = changeMap.get(bucket) || {
          openedCount: 0,
          openedMw: 0,
          closedCount: 0,
          closedMw: 0,
          dummyClosedMw: 0,
        };
        if (kind === 'construction') {
          changeInfo.openedCount += deltaCount;
          changeInfo.openedMw += namedMw;
        } else {
          changeInfo.closedCount += deltaCount;
          changeInfo.closedMw += namedMw;
          changeInfo.dummyClosedMw += dummyMw;
        }
        changeMap.set(bucket, changeInfo);
      }
    });

    Object.entries(latestByKind).forEach(([kind, latestMap]) => {
      latestMap.forEach((latest, summaryKey) => {
        const recordKey = `${kind}|${summaryKey}`;
        const currentChangeMap = yearChanges[kind].get(summaryKey);
        const entries = {};
        if (currentChangeMap && currentChangeMap.size > 0) {
          currentChangeMap.forEach((value, bucket) => {
            entries[bucket] = value;
          });
        }
        aggregates[kind].set(summaryKey, {
          key: recordKey,
          kind,
          site: latest.siteLabel,
          municipality: latest.municipality,
          summaryKey,
          entries,
          lastEntries: latest.lastEntries,
          lastYear: latest.lastYear,
          lastDate: latest.lastDate,
          lastBucket: latest.lastBucket,
        });
      });
    });

    return { aggregates, summary };
  }

  updateEventColumns(year) {
    const { aggregates, summary } = this.aggregateEventsUpTo(year);
    this.siteSummary = summary;

    ["construction", "closure"].forEach((kind) => {
      const list = this.eventLists[kind];
      if (!list) {
        return;
      }

      const bubbleMap = this.eventBubbles[kind];
      const activeKeys = new Set();
      const items = Array.from(aggregates[kind].values()).sort((a, b) => {
        if (a.lastYear !== b.lastYear) {
          return a.lastYear - b.lastYear;
        }
        return (a.lastDate || "").localeCompare(b.lastDate || "");
      });

      items.forEach((aggregate) => {
        activeKeys.add(aggregate.key);
        const bubble = this.upsertBubble(kind, aggregate, summary);
        if (bubble.parentNode) {
          bubble.parentNode.removeChild(bubble);
        }
        list.insertBefore(bubble, list.firstChild);
      });

      bubbleMap.forEach((bubble, key) => {
        if (!activeKeys.has(key)) {
          bubble.remove();
          bubbleMap.delete(key);
        }
      });

      if (activeKeys.size === 0) {
        if (!list.querySelector('.event-empty')) {
          const placeholder = document.createElement('li');
          placeholder.className = 'event-empty';
          const thumb = document.createElement('div');
          thumb.className = 'event-thumb';
          const yearEl = document.createElement('div');
          yearEl.className = 'event-year';
          yearEl.textContent = year;
          thumb.appendChild(yearEl);
          placeholder.appendChild(thumb);
          const body = document.createElement('div');
          body.className = 'event-body';
          body.textContent = 'No activity yet.';
          placeholder.appendChild(body);
          list.appendChild(placeholder);
        }
      } else {
        list.querySelectorAll('.event-empty').forEach((node) => node.remove());
      }
    });
  }

  classifyEvent(event) {
    const type = event.event_type;
    if (!type) {
      return null;
    }
    const lowerType = type.toLowerCase();
    if (lowerType === 'nuclear_build') {
      const deltaMw = Math.abs(Number(event.mw_added || 0));
      return {
        kind: 'construction',
        bucket: 'nuclear',
        deltaCount: 1,
        deltaMw,
        namedMw: deltaMw,
        dummyMw: 0,
      };
    }
    if (lowerType === 'fossil_build') {
      const deltaMw = Math.abs(Number(event.mw_added || 0));
      return {
        kind: 'construction',
        bucket: 'fossil',
        deltaCount: 1,
        deltaMw,
        namedMw: deltaMw,
        dummyMw: 0,
      };
    }
    if (lowerType === 'nuclear_closure') {
      const deltaMw = Math.abs(Number(event.mw_removed || 0));
      return {
        kind: 'closure',
        bucket: 'nuclear',
        deltaCount: 1,
        deltaMw,
        namedMw: deltaMw,
        dummyMw: 0,
      };
    }
    if (lowerType === 'fossil_closure') {
      const namedMw = Math.abs(Number(event.mw_removed || 0));
      const dummyMw = Math.abs(Number(event.dummy_capacity_closed_mw || event.dummy_fossil_capacity_closed_mw || 0));
      const combined = Math.abs(Number(event.fossil_capacity_closed_mw || namedMw + dummyMw));
      const countDelta = event && event.residual_only ? 0 : 1;
      return {
        kind: 'closure',
        bucket: 'fossil',
        deltaCount: countDelta,
        deltaMw: combined,
        namedMw,
        dummyMw,
      };
    }
    return null;
  }

  upsertBubble(kind, aggregate, summary) {
    const bubbleMap = this.eventBubbles[kind];
    let bubble = bubbleMap.get(aggregate.key);
    if (!bubble) {
      bubble = this.createBubbleNode();
      bubbleMap.set(aggregate.key, bubble);
    }
    this.updateBubbleNode(bubble, kind, aggregate, summary);
    return bubble;
  }

  createBubbleNode() {
    const item = document.createElement('li');
    const thumb = document.createElement('div');
    thumb.className = 'event-thumb';
    const img = document.createElement('img');
    thumb.appendChild(img);
    const yearEl = document.createElement('div');
    yearEl.className = 'event-year';
    thumb.appendChild(yearEl);
    item.appendChild(thumb);

    const body = document.createElement('div');
    body.className = 'event-body';
    const title = document.createElement('strong');
    body.appendChild(title);
    const metaContainer = document.createElement('div');
    metaContainer.className = 'event-meta-container';
    body.appendChild(metaContainer);
    item.appendChild(body);

    return item;
  }

  updateBubbleNode(node, kind, aggregate, summary) {
    node.dataset.key = aggregate.key;
    const img = node.querySelector('.event-thumb img');
    const yearEl = node.querySelector('.event-thumb .event-year');
    const icon = this.getIconForBucket(aggregate.lastBucket);
    if (img && icon) {
      img.src = icon.src;
      img.alt = icon.alt;
    }
    if (yearEl) {
      yearEl.textContent = aggregate.lastYear;
    }

    const title = node.querySelector('.event-body strong');
    if (title) {
      title.textContent = aggregate.site;
    }

    const metaContainer = node.querySelector('.event-meta-container');
    if (metaContainer) {
      metaContainer.innerHTML = '';
      const summaryLine = this.createSummaryLine(aggregate.summaryKey, aggregate.lastBucket, summary);
      if (summaryLine) {
        metaContainer.appendChild(summaryLine);
      }
      const preferredOrder = ['nuclear', 'fossil'];
      const entrySource = aggregate.entries && Object.keys(aggregate.entries).length > 0
        ? aggregate.entries
        : (aggregate.lastEntries || {});
      const buckets = Object.keys(entrySource);
      const sortedBuckets = preferredOrder.concat(
        buckets.filter((bucket) => !preferredOrder.includes(bucket))
      );
      const rendered = new Set();
      sortedBuckets.forEach((bucket) => {
        if (rendered.has(bucket)) {
          return;
        }
        rendered.add(bucket);
        const info = entrySource[bucket];
        const line = this.formatAggregateLines(kind, bucket, info);
        line.forEach((text) => {
          const metaLine = document.createElement('div');
          metaLine.className = 'event-meta';
          metaLine.textContent = text;
          metaContainer.appendChild(metaLine);
        });
      });
    }
  }

  formatAggregateLines(kind, bucket, info) {
    if (!info) {
      return [];
    }
    const lines = [];
    if (info.openedCount > 0) {
      const typeLabel = bucket === 'fossil' ? 'fossil' : bucket;
      const prettyType = typeLabel.charAt(0).toUpperCase() + typeLabel.slice(1);
      const plural = info.openedCount === 1 ? 'unit' : 'units';
      const magnitude = formatGWPrecise(info.openedMw / 1000, 2);
      lines.push(`Opened ${info.openedCount} ${prettyType} ${plural} (+${magnitude})`);
    }
    if (info.closedCount > 0) {
      const typeLabel = bucket === 'fossil' ? 'fossil' : bucket;
      const prettyType = typeLabel.charAt(0).toUpperCase() + typeLabel.slice(1);
      const plural = info.closedCount === 1 ? 'unit' : 'units';
      const magnitude = formatGWPrecise(info.closedMw / 1000, 2);
      lines.push(`Closed ${info.closedCount} ${prettyType} ${plural} (−${magnitude})`);
    }
    const dummyClosedMw = Number(info.dummyClosedMw || 0);
    if (dummyClosedMw > 0) {
      const magnitude = formatGWPrecise(dummyClosedMw / 1000, 2);
      lines.push(`Additional fossil retirements: −${magnitude}`);
    }
    return lines;
  }

  createSummaryLine(site, bucket, summary) {
    if (!summary || !summary.has(site)) {
      return null;
    }
    const bucketStats = summary.get(site).get(bucket);
    if (!bucketStats) {
      return null;
    }

    const netCount = Math.max(bucketStats.openedCount - bucketStats.closedCount, 0);
    const netMw = Math.max(bucketStats.openedMw - bucketStats.closedMw, 0);

    const summaryLine = document.createElement('div');
    summaryLine.className = 'event-meta';
    const typeLabelRaw = bucket === 'fossil' ? 'fossil' : bucket;
    const prettyType = typeLabelRaw.charAt(0).toUpperCase() + typeLabelRaw.slice(1);
    summaryLine.textContent = `Active ${prettyType} units: ${formatNumber(netCount, 0)} (${formatGWPrecise(netMw / 1000, 2)})`;
    return summaryLine;
  }

  resetEventColumns() {
    ["construction", "closure"].forEach((kind) => {
      const list = this.eventLists[kind];
      if (list) {
        list.innerHTML = '';
      }
      this.eventBubbles[kind].clear();
    });
  }

  getIconForBucket(bucket = '') {
    if (bucket.toLowerCase() === 'nuclear') {
      return { src: 'assets/nuclear_plant.svg', alt: 'Nuclear plant' };
    }
    return { src: 'assets/fossil_plant.png', alt: 'Fossil plant' };
  }
}

const setupTimeline = (years, views) => {
  const label = document.getElementById("year-label");
  const playButton = document.getElementById("play-toggle");

  let index = 0;
  let playing = false;
  let timer = null;

  const updateViews = (nextIndex) => {
    index = Math.min(Math.max(nextIndex, 0), years.length - 1);
    if (label) {
      label.textContent = years[index];
    }
    views.forEach((view) => view.update(index));
  };

  const stop = () => {
    playing = false;
    playButton.textContent = "Play";
    if (timer) {
      window.clearInterval(timer);
      timer = null;
    }
  };

  const tick = () => {
    if (index >= years.length - 1) {
      stop();
      return;
    }
    updateViews(index + 1);
  };

  const start = () => {
    if (playing) {
      stop();
      return;
    }
    playing = true;
    playButton.textContent = "Pause";
    timer = window.setInterval(tick, 1200);
  };

  playButton.addEventListener("click", () => {
    if (playing) {
      stop();
    } else {
      start();
    }
  });

  updateViews(0);
};

async function bootstrap() {
  const response = await fetch(DATA_URL, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Failed to load scenario data (${response.status})`);
  }
  const dataset = await response.json();
  const years = [];
  for (let year = dataset.metadata.start_year; year <= dataset.metadata.end_year; year += 1) {
    years.push(year);
  }

  const counterfactualRoot = document.querySelector('.scenario[data-scenario="counterfactual"]');
  const historicalRoot = document.querySelector('.scenario[data-scenario="historical"]');
  const metadata = dataset.metadata || {};
  const baselineInfo = {
    site: metadata.site_baselines || {},
    municipality: metadata.municipality_baselines || {},
  };

  const historicalView = new ScenarioView(historicalRoot, dataset.historical, years, {
    id: "historical",
    co2Mode: "absolute",
    baselines: baselineInfo,
  });
  const counterfactualView = new ScenarioView(counterfactualRoot, dataset.counterfactual, years, {
    id: "counterfactual",
    co2Mode: "difference",
    baselines: baselineInfo,
  });

  historicalView.setComparisonSeries({
    co2: counterfactualView.series.co2,
    clean: counterfactualView.series.clean,
  });
  counterfactualView.setComparisonSeries({
    co2: historicalView.series.co2,
    clean: historicalView.series.clean,
  });

  const CO2_DOMAIN_MAX = 350;
  const CLEAN_DOMAIN_MAX = 1000;
  historicalView.charts.co2.setDomainMax(CO2_DOMAIN_MAX);
  counterfactualView.charts.co2.setDomainMax(CO2_DOMAIN_MAX);
  historicalView.charts.clean.setDomainMax(CLEAN_DOMAIN_MAX);
  counterfactualView.charts.clean.setDomainMax(CLEAN_DOMAIN_MAX);

  setupTimeline(years, [counterfactualView, historicalView]);
}

bootstrap().catch((error) => {
  console.error(error);
  const main = document.querySelector("main");
  const warning = document.createElement("div");
  warning.className = "load-error";
  const details = error instanceof Error ? error.message : String(error);
  warning.textContent = `Unable to load scenario data (${details}). Please run through a web server for local files.`;
  main.prepend(warning);
});

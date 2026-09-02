/*
 * Funemployment Destroyer — frontend
 *
 * Organised into sections:
 *   CONFIG            constants
 *   STORAGE           localStorage-backed personal state (favorite / applied / hidden)
 *   DATA              loading + normalising jobs.json
 *   DERIVE            computed helpers (isNew, matching, filtering, sorting)
 *   RENDER            DOM output
 *   UI                event wiring + UI state
 *
 * jobs.json is treated as a read-only feed. Nothing here writes to it, so a
 * Python collector can regenerate the file without any frontend changes.
 */

(function () {
  'use strict';

  /* ------------------------------------------------------------------ CONFIG */

  var CONFIG = {
    dataUrl: './data/jobs.json',        // relative — works under /funemployment-destroyer/
    fallbackUrl: './data/jobs.js',      // same data as a <script>, for file://
    newWindowHours: 72,
    pageSize: 60,               // cards rendered before 'Show more'
    storageKey: 'fd.state.v1',
    filterFields: [
      'type',
      'category',
      'location',
      'workMode',
      'degreeRequirement',
      'experienceLevel'
    ],
    // Canonical ordering for select options that have a known vocabulary.
    vocab: {
      type: ['Internship', 'Full Time'],
      workMode: ['On site', 'Hybrid', 'Remote', 'Not specified'],
      degreeRequirement: [
        'No degree required',
        'Degree preferred',
        'Currently enrolled',
        'Degree required',
        'Not specified'
      ]
    },
    emptyStates: {
      filtered: {
        title: 'No jobs survived your extremely specific standards.',
        body: 'Loosen a filter or two. The perfect role exists, it just may not be filed under every box you ticked.'
      },
      search: {
        title: 'Nothing matches that search.',
        body: 'Try a company, a job title, a category, or a city instead.'
      },
      favorites: {
        title: 'No favorites yet.',
        body: 'Star the roles worth a real application. They will gather here.'
      },
      applied: {
        title: 'Nothing marked applied.',
        body: 'The funemployment remains undefeated. For now.'
      },
      new: {
        title: 'Nothing new in the last 72 hours.',
        body: 'The radar is quiet. Check the other tabs while the world catches up.'
      },
      none: {
        title: 'No opportunities loaded.',
        body: 'jobs.json came back empty. Once the collector runs, this fills itself.'
      },
      error: {
        title: 'Could not load the job data.',
        body: 'Neither data/jobs.json nor data/jobs.js could be read. Run scripts/collect.py to generate them, or serve this folder over http.'
      }
    }
  };

  var TABS = {
    all:         function () { return true; },
    internships: function (job) { return job.type === 'Internship'; },
    fulltime:    function (job) { return job.type === 'Full Time'; },
    'new':       function (job) { return job.isNew; },
    favorites:   function (job) { return Storage.has('favorites', job.id); },
    applied:     function (job) { return Storage.has('applied', job.id); }
  };

  /* ----------------------------------------------------------------- STORAGE */

  var Storage = {
    state: { favorites: [], applied: [], hidden: [] },

    load: function () {
      try {
        var raw = window.localStorage.getItem(CONFIG.storageKey);
        if (!raw) return;
        var parsed = JSON.parse(raw);
        ['favorites', 'applied', 'hidden'].forEach(function (key) {
          if (Array.isArray(parsed[key])) Storage.state[key] = parsed[key].slice();
        });
      } catch (err) {
        // Corrupt payload or storage disabled (private mode): fall back to defaults.
        console.warn('[FD] could not read saved state:', err);
      }
    },

    save: function () {
      try {
        window.localStorage.setItem(CONFIG.storageKey, JSON.stringify(Storage.state));
      } catch (err) {
        console.warn('[FD] could not save state:', err);
      }
    },

    has: function (key, id) {
      return Storage.state[key].indexOf(id) !== -1;
    },

    toggle: function (key, id) {
      var list = Storage.state[key];
      var i = list.indexOf(id);
      if (i === -1) list.push(id); else list.splice(i, 1);
      Storage.save();
      return i === -1;
    },

    remove: function (key, id) {
      var i = Storage.state[key].indexOf(id);
      if (i !== -1) { Storage.state[key].splice(i, 1); Storage.save(); }
    },

    clear: function (key) {
      Storage.state[key] = [];
      Storage.save();
    }
  };

  /* -------------------------------------------------------------------- DATA */

  var UI = {
    jobs: [],
    generatedAt: null,
    tab: 'all',
    query: '',
    sort: 'newest',
    page: 1,      // how many pages of results are currently rendered
    filters: {}   // field -> selected value ('' means any)
  };

  function loadJobs() {
    return fetch(CONFIG.dataUrl, { cache: 'no-cache' })
      .then(function (res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.json();
      })
      .catch(function (err) {
        // Opening index.html straight from disk puts us on file://, where
        // fetch() is blocked by CORS but a <script> tag still loads. Fall
        // back to the generated jobs.js so double-clicking the file works.
        console.warn('[FD] fetch failed (' + err.message + '); trying ' + CONFIG.fallbackUrl);
        return loadFallback();
      })
      .then(function (payload) {
        // Accept either a bare array or { generatedAt, jobs: [...] } so the
        // future generator can pick either shape.
        var list = Array.isArray(payload) ? payload : (payload && payload.jobs) || [];
        UI.generatedAt = (payload && payload.generatedAt) || null;
        return list.map(normaliseJob).filter(function (job) { return !!job.id; });
      });
  }

  function loadFallback() {
    return new Promise(function (resolve, reject) {
      if (window.FD_JOBS) return resolve(window.FD_JOBS);

      var script = document.createElement('script');
      script.src = CONFIG.fallbackUrl;
      script.onload = function () {
        if (window.FD_JOBS) resolve(window.FD_JOBS);
        else reject(new Error('jobs.js loaded but set no data'));
      };
      script.onerror = function () {
        reject(new Error('could not load ' + CONFIG.fallbackUrl));
      };
      document.head.appendChild(script);
    });
  }

  function normaliseJob(raw) {
    var job = {
      id: str(raw.id),
      company: str(raw.company) || 'Unknown company',
      title: str(raw.title) || 'Untitled role',
      type: str(raw.type) || 'Full Time',
      category: str(raw.category) || 'Not specified',
      season: str(raw.season),
      location: str(raw.location) || 'Not specified',
      workMode: str(raw.workMode) || 'Not specified',
      url: str(raw.url),
      postedAt: str(raw.postedAt),
      firstSeen: str(raw.firstSeen) || str(raw.postedAt),
      degreeRequirement: str(raw.degreeRequirement) || 'Not specified',
      experienceLevel: str(raw.experienceLevel) || 'Not specified',
      status: str(raw.status) || 'open',
      priority: typeof raw.priority === 'number' ? raw.priority : 0,
      source: str(raw.source),
      notes: str(raw.notes)
    };
    job.firstSeenTime = toTime(job.firstSeen);
    job.postedTime = toTime(job.postedAt);
    // Recency everywhere is measured from when the company posted the role,
    // not when this collector happened to notice it.
    job.isNew = isNew(job.postedTime || job.firstSeenTime);
    job.haystack = [job.company, job.title, job.category, job.location]
      .join(' ').toLowerCase();
    return job;
  }

  function str(value) {
    return typeof value === 'string' ? value.trim() : '';
  }

  function toTime(value) {
    if (!value) return 0;
    var t = Date.parse(value);
    return isNaN(t) ? 0 : t;
  }

  /* ------------------------------------------------------------------ DERIVE */

  function isNew(time) {
    if (!time) return false;
    return (Date.now() - time) <= CONFIG.newWindowHours * 60 * 60 * 1000;
  }

  function visibleJobs() {
    // Everything except hidden — the base pool for stats and tab counts.
    return UI.jobs.filter(function (job) { return !Storage.has('hidden', job.id); });
  }

  function matchesSearch(job, query) {
    if (!query) return true;
    return query.split(/\s+/).every(function (term) {
      return job.haystack.indexOf(term) !== -1;
    });
  }

  function matchesFilters(job) {
    return CONFIG.filterFields.every(function (field) {
      var wanted = UI.filters[field];
      return !wanted || job[field] === wanted;
    });
  }

  function applyView(jobs) {
    var tabTest = TABS[UI.tab] || TABS.all;
    var query = UI.query.trim().toLowerCase();
    return jobs.filter(function (job) {
      return tabTest(job) && matchesFilters(job) && matchesSearch(job, query);
    });
  }

  function sortJobs(jobs) {
    var sorted = jobs.slice();
    switch (UI.sort) {
      case 'oldest':
        sorted.sort(function (a, b) { return sortTime(a) - sortTime(b); });
        break;
      case 'company':
        sorted.sort(function (a, b) {
          return a.company.localeCompare(b.company) || a.title.localeCompare(b.title);
        });
        break;
      case 'priority':
        sorted.sort(function (a, b) {
          return (b.priority - a.priority) || (sortTime(b) - sortTime(a));
        });
        break;
      default: // newest
        sorted.sort(function (a, b) { return sortTime(b) - sortTime(a); });
    }
    return sorted;
  }

  // Posting date is the ordering key. firstSeen is only a fallback for the
  // rare posting whose source published no date at all.
  function sortTime(job) {
    return job.postedTime || job.firstSeenTime;
  }

  function activeFilterCount() {
    return CONFIG.filterFields.filter(function (f) { return !!UI.filters[f]; }).length;
  }

  /* ------------------------------------------------------------------ RENDER */

  var el = {};

  function cacheElements() {
    el.stats = {
      total: document.getElementById('stat-total'),
      newly: document.getElementById('stat-new'),
      internships: document.getElementById('stat-internships'),
      fulltime: document.getElementById('stat-fulltime')
    };
    el.search = document.getElementById('search');
    el.tabs = document.getElementById('tabs');
    el.filters = document.getElementById('filters');
    el.toggleFilters = document.getElementById('toggle-filters');
    el.filterCount = document.getElementById('filter-count');
    el.clearFilters = document.getElementById('clear-filters');
    el.sort = document.getElementById('sort');
    el.results = document.getElementById('results');
    el.resultCount = document.getElementById('result-count');
    el.hiddenDrawer = document.getElementById('hidden-drawer');
    el.hiddenList = document.getElementById('hidden-list');
    el.hiddenSummary = document.getElementById('hidden-summary');
    el.restoreAll = document.getElementById('restore-all');
    el.dataStamp = document.getElementById('data-stamp');
    el.template = document.getElementById('job-card-template');
  }

  function renderStats(pool) {
    el.stats.total.textContent = pool.length;
    el.stats.newly.textContent = pool.filter(function (j) { return j.isNew; }).length;
    el.stats.internships.textContent = pool.filter(TABS.internships).length;
    el.stats.fulltime.textContent = pool.filter(TABS.fulltime).length;
  }

  function renderTabCounts(pool) {
    Object.keys(TABS).forEach(function (name) {
      var node = el.tabs.querySelector('[data-count="' + name + '"]');
      if (node) node.textContent = pool.filter(TABS[name]).length;
    });
  }

  function renderFilterOptions() {
    CONFIG.filterFields.forEach(function (field) {
      var select = el.filters.querySelector('[data-filter="' + field + '"]');
      if (!select) return;

      var values = uniqueValues(field);
      var current = UI.filters[field] || '';

      select.innerHTML = '';
      select.appendChild(makeOption('', 'Any'));
      values.forEach(function (value) {
        select.appendChild(makeOption(value, value));
      });
      select.value = values.indexOf(current) === -1 ? '' : current;
      UI.filters[field] = select.value;
    });
  }

  function uniqueValues(field) {
    var seen = {};
    UI.jobs.forEach(function (job) {
      if (job[field]) seen[job[field]] = true;
    });
    var values = Object.keys(seen);
    var order = CONFIG.vocab[field];
    if (order) {
      // Known vocabulary first, in canonical order; anything unexpected after.
      var known = order.filter(function (v) { return values.indexOf(v) !== -1; });
      var extra = values.filter(function (v) { return order.indexOf(v) === -1; }).sort();
      return known.concat(extra);
    }
    return values.sort(function (a, b) { return a.localeCompare(b); });
  }

  function makeOption(value, label) {
    var opt = document.createElement('option');
    opt.value = value;
    opt.textContent = label;
    return opt;
  }

  function renderJobs(jobs) {
    el.results.innerHTML = '';

    if (!jobs.length) {
      el.results.appendChild(renderEmptyState());
      return;
    }

    // The live feed runs to ~1,500 postings. Rendering every card up front
    // costs a visible pause on mobile, so grow the list on demand instead.
    var limit = Math.min(jobs.length, UI.page * CONFIG.pageSize);
    var frag = document.createDocumentFragment();
    for (var i = 0; i < limit; i++) {
      frag.appendChild(renderCard(jobs[i]));
    }
    el.results.appendChild(frag);

    if (limit < jobs.length) {
      el.results.appendChild(renderShowMore(jobs.length - limit));
    }
  }

  function renderShowMore(remaining) {
    var wrap = document.createElement('div');
    wrap.className = 'show-more';

    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'btn';
    btn.textContent = 'Show more (' + remaining + ' left)';
    btn.addEventListener('click', function () {
      UI.page += 1;
      render();
    });

    wrap.appendChild(btn);
    return wrap;
  }

  function renderCard(job) {
    var node = el.template.content.firstElementChild.cloneNode(true);
    node.dataset.id = job.id;

    field(node, 'company').textContent = job.company;
    field(node, 'title').textContent = job.title;
    field(node, 'type').textContent = job.type;
    field(node, 'category').textContent = job.category;
    field(node, 'location').textContent = job.location;
    field(node, 'workMode').textContent = job.workMode;
    // The degree chip only earns its place when it tells you something you
    // could act on. Internships are all "currently enrolled" by definition,
    // and a full-time role that merely prefers a degree is not a gate -- so
    // the chip appears solely for full-time roles with no degree requirement.
    var degreeChip = field(node, 'degreeRequirement');
    var showDegree = job.type !== 'Internship' &&
                     job.degreeRequirement === 'No degree required';
    degreeChip.textContent = job.degreeRequirement;
    degreeChip.hidden = !showDegree;
    degreeChip.classList.toggle('chip-degree', showDegree);
    field(node, 'experienceLevel').textContent = job.experienceLevel;

    var season = field(node, 'season');
    season.hidden = !job.season;
    season.textContent = job.season;

    field(node, 'new').hidden = !job.isNew;
    field(node, 'priority').textContent = 'Priority ' + job.priority + '/5';

    var notes = field(node, 'notes');
    notes.textContent = job.notes;
    notes.hidden = !job.notes;

    var posted = field(node, 'postedAt');
    posted.textContent = job.postedAt ? 'Posted ' + formatDateTime(job.postedAt) : '';
    posted.hidden = !job.postedAt;

    var apply = field(node, 'url');
    if (job.url) {
      apply.href = job.url;
      apply.setAttribute('aria-label', 'Apply to ' + job.title + ' at ' + job.company);
    } else {
      apply.removeAttribute('href');
      apply.textContent = 'No link';
    }

    var fav = node.querySelector('[data-action="favorite"]');
    var applied = node.querySelector('[data-action="applied"]');
    fav.setAttribute('aria-pressed', String(Storage.has('favorites', job.id)));
    applied.setAttribute('aria-pressed', String(Storage.has('applied', job.id)));
    node.classList.toggle('is-applied', Storage.has('applied', job.id));

    return node;
  }

  function field(root, name) {
    return root.querySelector('[data-field="' + name + '"]');
  }

  function formatDate(iso) {
    var t = toTime(iso);
    if (!t) return 'date unknown';
    var d = new Date(t);
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
  }

  function formatDateTime(iso) {
    var t = toTime(iso);
    if (!t) return 'date unknown';
    var d = new Date(t);
    var date = d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });

    // A date-only value ("2026-09-01") carries no real time of day -- showing
    // "12:00 AM" for it would be inventing precision the source never had.
    if (!hasTimeComponent(iso)) return date;

    var time = d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
    return date + ' at ' + time;
  }

  function hasTimeComponent(iso) {
    return typeof iso === 'string' && iso.indexOf('T') !== -1;
  }

  function renderEmptyState() {
    var copy;
    if (!UI.jobs.length) copy = CONFIG.emptyStates.none;
    else if (UI.tab === 'favorites' && !Storage.state.favorites.length) copy = CONFIG.emptyStates.favorites;
    else if (UI.tab === 'applied' && !Storage.state.applied.length) copy = CONFIG.emptyStates.applied;
    else if (UI.tab === 'new' && !UI.query && !activeFilterCount()) copy = CONFIG.emptyStates['new'];
    else if (activeFilterCount()) copy = CONFIG.emptyStates.filtered;
    else copy = CONFIG.emptyStates.search;

    return buildEmpty(copy, activeFilterCount() > 0 || !!UI.query);
  }

  function buildEmpty(copy, showReset) {
    var box = document.createElement('div');
    box.className = 'empty';

    var h = document.createElement('h2');
    h.textContent = copy.title;
    box.appendChild(h);

    var p = document.createElement('p');
    p.textContent = copy.body;
    box.appendChild(p);

    if (showReset) {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'btn ghost';
      btn.textContent = 'Clear search and filters';
      btn.addEventListener('click', resetSearchAndFilters);
      box.appendChild(btn);
    }
    return box;
  }

  function renderHiddenDrawer() {
    var ids = Storage.state.hidden;
    var known = UI.jobs.filter(function (job) { return ids.indexOf(job.id) !== -1; });

    el.hiddenDrawer.hidden = known.length === 0;
    if (!known.length) return;

    el.hiddenSummary.textContent =
      known.length + ' hidden ' + (known.length === 1 ? 'opportunity' : 'opportunities');

    el.hiddenList.innerHTML = '';
    known.forEach(function (job) {
      var li = document.createElement('li');

      var label = document.createElement('span');
      label.textContent = job.company + ' — ' + job.title;
      li.appendChild(label);

      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'btn ghost';
      btn.textContent = 'Restore';
      btn.addEventListener('click', function () {
        Storage.remove('hidden', job.id);
        render();
      });
      li.appendChild(btn);

      el.hiddenList.appendChild(li);
    });
  }

  function renderResultCount(shown, pool) {
    // Agrees with the pool, not the shown count: "1 of 1499 opportunities".
    var noun = pool.length === 1 ? 'opportunity' : 'opportunities';
    var text = 'Showing ' + shown + ' of ' + pool.length + ' ' + noun;
    var hiddenCount = Storage.state.hidden.length;
    if (hiddenCount) text += ' · ' + hiddenCount + ' hidden';
    el.resultCount.textContent = text;
  }

  function render() {
    var pool = visibleJobs();
    var shown = sortJobs(applyView(pool));

    renderStats(pool);
    renderTabCounts(pool);
    renderJobs(shown);
    renderResultCount(shown.length, pool);
    renderHiddenDrawer();

    var count = activeFilterCount();
    el.filterCount.hidden = count === 0;
    el.filterCount.textContent = count;
  }

  /* ---------------------------------------------------------------------- UI */

  function resetSearchAndFilters() {
    UI.query = '';
    el.search.value = '';
    UI.page = 1;
    CONFIG.filterFields.forEach(function (field) {
      UI.filters[field] = '';
      var select = el.filters.querySelector('[data-filter="' + field + '"]');
      if (select) select.value = '';
    });
    render();
  }

  function setTab(name) {
    if (!TABS[name]) return;
    UI.tab = name;
    UI.page = 1;
    Array.prototype.forEach.call(el.tabs.querySelectorAll('.tab'), function (btn) {
      var active = btn.dataset.tab === name;
      btn.classList.toggle('is-active', active);
      if (active) btn.setAttribute('aria-current', 'page');
      else btn.removeAttribute('aria-current');
    });
    render();
  }

  function bindEvents() {
    el.search.addEventListener('input', debounce(function () {
      UI.query = el.search.value;
      UI.page = 1;
      render();
    }, 120));

    el.tabs.addEventListener('click', function (event) {
      var btn = event.target.closest('.tab');
      if (btn) setTab(btn.dataset.tab);
    });

    el.filters.addEventListener('change', function (event) {
      var select = event.target.closest('[data-filter]');
      if (!select) return;
      UI.filters[select.dataset.filter] = select.value;
      UI.page = 1;
      render();
    });

    el.toggleFilters.addEventListener('click', function () {
      var open = el.filters.hidden;
      el.filters.hidden = !open;
      el.toggleFilters.setAttribute('aria-expanded', String(open));
    });

    el.clearFilters.addEventListener('click', resetSearchAndFilters);

    el.sort.addEventListener('change', function () {
      UI.sort = el.sort.value;
      UI.page = 1;
      render();
    });

    el.results.addEventListener('click', function (event) {
      var btn = event.target.closest('[data-action]');
      if (!btn) return;
      var card = btn.closest('.card');
      if (!card) return;
      var id = card.dataset.id;

      switch (btn.dataset.action) {
        case 'favorite': Storage.toggle('favorites', id); break;
        case 'applied':  Storage.toggle('applied', id); break;
        case 'hide':
          Storage.toggle('hidden', id);
          // A hidden job should never linger in favorites-only views either.
          break;
      }
      render();
    });

    el.restoreAll.addEventListener('click', function () {
      Storage.clear('hidden');
      render();
    });
  }

  function debounce(fn, wait) {
    var timer;
    return function () {
      clearTimeout(timer);
      timer = setTimeout(fn, wait);
    };
  }

  function showFatal(copy) {
    el.results.innerHTML = '';
    el.results.appendChild(buildEmpty(copy, false));
    el.resultCount.textContent = '';
  }

  function init() {
    cacheElements();
    Storage.load();
    CONFIG.filterFields.forEach(function (f) { UI.filters[f] = ''; });
    bindEvents();

    loadJobs()
      .then(function (jobs) {
        UI.jobs = jobs;
        renderFilterOptions();
        if (UI.generatedAt) {
          el.dataStamp.textContent = 'Job data last generated ' + formatDate(UI.generatedAt) + '.';
        }
        render();
      })
      .catch(function (err) {
        console.error('[FD] failed to load jobs:', err);
        showFatal(CONFIG.emptyStates.error);
      });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();

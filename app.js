const REQUIRED_TOOLS = [
  "prepare_recovery_context",
  "propose_recovery_plan",
  "execute_approved_action",
  "verify_action_status",
  "find_recovery_options",
  "find_pickup_options",
  "reset_demo_scenario",
];

const TOGGLEABLE_MODULES = new Set(["travel", "calendar", "delivery", "reservations", "messaging"]);
const ACTIVITY_STORAGE_KEY = "ripple-mcp-activity-v1";

const TOOL_PURPOSES = {
  "tools/list": "Discovery: the browser asks the MCP server which tools it actually exposes.",
  prepare_recovery_context: "Context: configure this demo and fetch all relevant mock service data in one round trip.",
  find_pickup_options: "Comparison: filter mock options by deadline, budget, and availability, then explain the option that best matches the user's stated priority.",
  propose_recovery_plan: "Planning: turn the current service state into a reviewable proposal; this does not execute it.",
  execute_approved_action: "Approval: perform or decline one selected action in the mock service.",
  verify_action_status: "Verification: query the action record after execution and return evidence.",
  reset_demo_scenario: "Reset: restore the mock services and clear pending plans.",
};

const SCENARIOS = {
  pickup_risk: {
    title: "Pickup at risk",
    detail: "A delayed commute threatens a school pickup deadline. Compare a backup contact and a mock ride.",
    request: "My train is delayed by 40 minutes. I need to pick up Sam by 6:00 PM. Find options under $25.",
    heading: "A late commute puts pickup at risk.",
    status: "PICKUP AT RISK",
  },
  flight_delay: {
    title: "Flight delayed",
    detail: "A two-hour delay affects pickup, dinner, groceries, and reminders.",
    request: "My flight is delayed by two hours. Fix whatever this messes up tonight, but don't cancel dinner.",
    heading: "A delayed flight disrupts tonight.",
    status: "DELAYED",
  },
  flight_cancelled: {
    title: "Flight cancelled",
    detail: "Find another flight, coordinate airport pickup, and update arrival plans.",
    request: "My flight was cancelled. Find the next flight, update pickup, and keep dinner if possible.",
    heading: "A cancelled flight changes the evening.",
    status: "CANCELLED",
  },
  delivery_disruption: {
    title: "Delivery running late",
    detail: "A late grocery window affects the household and its reminders.",
    request: "My grocery delivery is delayed until late tonight. Find a better window and let the household know.",
    heading: "A late delivery affects the household.",
    status: "RUNNING LATE",
  },
  meeting_overrun: {
    title: "Meeting running over",
    detail: "A late meeting overlaps dinner and changes the plans around it.",
    request: "My meeting is running late and conflicts with dinner. Find a later time, update my reminder, and draft a note to Maya.",
    heading: "A meeting overrun conflicts with dinner.",
    status: "RUNNING LATE",
  },
};

const state = {
  tools: new Set(),
  toolCatalog: new Map(),
  serviceAvailability: {
    travel: true,
    calendar: true,
    delivery: true,
    reservations: true,
    messaging: true,
  },
  plan: null,
  context: null,
  busy: false,
  scenario: "pickup_risk",
  pickupOptions: null,
};

const SERVICE_MODULES = [
  { id: "travel", label: "Travel", tools: ["get_travel_status", "find_pickup_options"], description: "Flight status and pickup transport options" },
  { id: "calendar", label: "Calendar", tools: ["get_calendar_events"], description: "Read commitments; approved updates use the shared executor" },
  { id: "delivery", label: "Delivery", tools: ["get_delivery_status", "find_alternatives", "find_recovery_options"], description: "Delivery status and recovery options" },
  { id: "reservations", label: "Reservations", tools: ["find_alternatives"], description: "Dinner availability and booking changes" },
  { id: "messaging", label: "Messaging", tools: ["execute_approved_action"], description: "Shared action executor routes approved message actions" },
  { id: "planning", label: "Ripple planner", tools: ["prepare_recovery_context", "find_pickup_options", "propose_recovery_plan"], description: "Context gathering, option comparison, and plan proposals" },
  { id: "preferences", label: "Preferences", tools: ["get_user_constraints"], description: "Protected commitments and user constraints" },
];

const buildButton = document.querySelector("#build-plan");
const planSection = document.querySelector("#plan-section");
const themeToggle = document.querySelector("#theme-toggle");
const delayLabel = document.querySelector("#flight-delay-label");

function parseToolResult(text, toolName) {
  try {
    const value = JSON.parse(text);
    if (value && typeof value === "object" && value.error) {
      throw new Error(value.error);
    }
    return value;
  } catch (error) {
    throw new Error(`${toolName}: ${error.message}`);
  }
}

function inferScenario(text) {
  const normalized = text.toLowerCase();
  const clauses = normalized.split(/\b(?:and|but|while|then)\b|[,.!?;]+/);
  const flightClause = clauses.find((clause) => /\b(flight|airline|airport)\b/.test(clause));
  if (flightClause && /\b(cancelled|canceled|cancellation)\b/.test(flightClause)) {
    return "flight_cancelled";
  }
  if (
    clauses.some(
      (clause) =>
        /\b(meeting|appointment|call)\b/.test(clause) &&
        /\b(late|over|running)\b/.test(clause),
    )
  ) {
    return "meeting_overrun";
  }
  if (/\b(grocer|delivery|deliveries|parcel)\b/.test(normalized)) return "delivery_disruption";
  if (/\b(pickup|school|child|commute|train|caregiver|handoff)\b/.test(normalized)) return "pickup_risk";
  return "flight_delay";
}

function selectScenario(scenario, updateRequest = true) {
  const details = SCENARIOS[scenario];
  if (!details) return;
  const changed = state.scenario !== scenario;
  state.scenario = scenario;
  document.querySelectorAll(".scenario-choice").forEach((button) => {
    const selected = button.dataset.scenario === scenario;
    button.classList.toggle("selected", selected);
    button.setAttribute("aria-pressed", String(selected));
  });
  document.querySelector("#scenario-card-title").textContent = details.title;
  document.querySelector("#scenario-card-detail").textContent = details.detail;
  document.querySelector("#scenario-title").textContent = details.heading;
  document.querySelector("#scenario-status").textContent = details.status;
  if (updateRequest) document.querySelector("#request-input").value = details.request;
  const isPickup = scenario === "pickup_risk";
  document.querySelector("#pickup-settings").hidden = !isPickup;
  document.querySelector("#non-pickup-settings").hidden = isPickup;
  document.querySelector("#delay-setting").hidden = !isPickup && scenario !== "flight_delay";
  document.querySelector("#delay-setting").firstChild.textContent = isPickup ? "Commute delay (minutes)" : "Flight delay (minutes)";
  buildButton.textContent = isPickup ? "Find safe pickup options →" : "Find the ripple effects →";
  if (isPickup && (updateRequest || changed)) document.querySelector("#delay-minutes").value = "40";
  if (changed || !isPickup) document.querySelector("#pickup-options-panel").hidden = true;
  updateDelayLabel(extractDelayMinutes(document.querySelector("#request-input").value));
}

function logActivity(toolName, args, result, failed = false) {
  const entry = {
    id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
    timestamp: new Date().toISOString(),
    toolName,
    purpose: TOOL_PURPOSES[toolName] || "MCP tool request and returned result.",
    failed,
    arguments: args,
    result,
  };
  try {
    const saved = localStorage.getItem(ACTIVITY_STORAGE_KEY);
    const entries = saved ? JSON.parse(saved) : [];
    if (!Array.isArray(entries)) throw new Error("Saved MCP activity has an invalid format.");
    entries.push(entry);
    localStorage.setItem(ACTIVITY_STORAGE_KEY, JSON.stringify(entries.slice(-200)));
  } catch (error) {
    document.querySelector("#voice-note").textContent =
      `MCP activity ran, but Ripple couldn't save it for the Logs page: ${error.message}`;
  }
}

function renderServiceBoard() {
  const board = document.querySelector("#service-board");
  board.replaceChildren();
  SERVICE_MODULES.forEach((module) => {
    const discovered = module.tools.filter((name) => state.tools.has(name));
    const card = document.createElement("article");
    card.className = `service-module${discovered.length ? "" : " unavailable"}`;
    card.dataset.service = module.id;
    const heading = document.createElement("div");
    heading.className = "service-module-heading";
    const title = document.createElement("strong");
    title.textContent = module.label;
    const status = document.createElement("span");
    const moduleAvailable = Boolean(discovered.length) && (state.serviceAvailability[module.id] ?? true);
    status.className = `module-status ${moduleAvailable ? "online" : "offline"}`;
    status.textContent = !discovered.length ? "NO TOOL" : moduleAvailable ? "SIMULATED · ON" : "SIMULATED · OFF";
    heading.append(title, status);
    const description = document.createElement("p");
    description.textContent =
      module.id === "delivery" && state.context?.delivery
        ? `${state.context.delivery.provider}: ${state.context.delivery.provider_available ? "available" : "offline"} · QuickBasket backup: ${state.context.delivery.backup_provider_available ? "available" : "offline"}`
        : module.description;
    const toolList = document.createElement("div");
    toolList.className = "module-tools";
    if (!discovered.length) {
      const empty = document.createElement("span");
      empty.className = "tool-chip missing";
      empty.textContent = "No matching tool discovered";
      toolList.append(empty);
    } else {
      discovered.forEach((name) => {
        const chip = document.createElement("span");
        chip.className = "tool-chip";
        chip.textContent = name;
        chip.title = state.toolCatalog.get(name)?.description || name;
        toolList.append(chip);
      });
    }
    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "module-toggle";
    const canToggle = TOGGLEABLE_MODULES.has(module.id);
    toggle.disabled = !discovered.length || !canToggle || state.busy;
    toggle.textContent = moduleAvailable ? "Disconnect demo module" : "Reconnect demo module";
    if (!canToggle) toggle.hidden = true;
    toggle.addEventListener("click", () => {
      state.serviceAvailability[module.id] = !state.serviceAvailability[module.id];
      renderServiceBoard();
    });
    card.append(heading, description, toolList, toggle);
    board.append(card);
  });
  document.querySelector("#control-server-status").textContent =
    `ONE MCP SERVER · ${state.tools.size} TOOLS DISCOVERED`;
}

async function callRippleTool(name, args = {}) {
  if (!state.tools.has(name)) {
    throw new Error(`The connected Ripple MCP server did not advertise ${name}.`);
  }
  try {
    const text = await window.dominoMcp.callTool(name, args);
    const result = parseToolResult(text, name);
    logActivity(name, args, result);
    return result;
  } catch (error) {
    logActivity(name, args, { error: error.message }, true);
    throw error;
  }
}

function setBusy(busy, statusText = "") {
  state.busy = busy;
  buildButton.disabled = busy;
  document.querySelector("#reset-scenario").disabled = busy;
  document.querySelector("#mcp-status").disabled = busy;
  document.querySelectorAll(".scenario-choice").forEach((button) => {
    button.disabled = busy;
  });
  document
    .querySelectorAll(
    "#request-input, #voice-input, #delay-minutes, #dinner-option, #keep-dinner, #delivery-provider-available, #delivery-backup-available, #pickup-deadline, #pickup-budget, #pickup-priority, #prepare-pickup-plan, input[name='pickup-option']",
    )
    .forEach((input) => {
      input.disabled =
        busy ||
        (input.type === "radio" &&
          (input.closest(".pickup-option")?.classList.contains("unavailable") ||
            state.pickupOptions?.planPrepared)) ||
        (input.id === "prepare-pickup-plan" &&
          (!state.pickupOptions?.options.some((option) => option.eligible) ||
            state.pickupOptions?.planPrepared));
    });
  document.querySelectorAll(".action-decisions button").forEach((button) => {
    const card = button.closest(".plan-action");
    button.disabled =
      busy ||
      (button.classList.contains("action-recovery")
        ? button.hidden
        : card.dataset.resolved === "true");
  });
  document.querySelectorAll(".module-toggle").forEach((button) => {
    const moduleId = button.closest(".service-module")?.dataset.service;
    const module = SERVICE_MODULES.find((candidate) => candidate.id === moduleId);
    button.disabled =
      busy ||
      !module ||
      !TOGGLEABLE_MODULES.has(module.id) ||
      !module.tools.some((tool) => state.tools.has(tool));
  });
  if (statusText) document.querySelector("#voice-note").textContent = statusText;
}

function updateImpact(service, status, detail) {
  const item = [...document.querySelectorAll(".impact-item")].find(
    (candidate) => candidate.dataset.service === service,
  );
  if (!item) return;
  item.querySelector(".impact-state").textContent = status;
  item.querySelector("small").textContent = detail;
  item.classList.toggle("complete", status === "READY");
  item.classList.toggle("error", status === "ERROR");
}

function resetImpactStatuses() {
  document.querySelectorAll(".impact-item").forEach((item) => {
    item.querySelector(".impact-state").textContent = "WAITING";
    item.classList.remove("complete", "error");
  });
}

function updateConstraintPreview() {
  document.querySelector("#constraint-preview").textContent = state.scenario === "pickup_risk"
    ? `Pickup by ${document.querySelector("#pickup-deadline").value} · Max $${document.querySelector("#pickup-budget").value} · ${document.querySelector("#pickup-priority").value === "arrival_buffer" ? "Prioritize arrival buffer" : "Prioritize lower cost"} · Ask before contacting`
    : `${document.querySelector("#keep-dinner").checked ? "Keep dinner protected" : "Dinner may be changed"} · Ask before sending messages`;
}

function extractDelayMinutes(text) {
  const normalized = text.toLowerCase();
  const hours = normalized.match(/(\d+)\s*(?:hours?|hrs?|h)\b/);
  const minutes = normalized.match(/(\d+)\s*(?:minutes?|mins?)\b/);
  if (!hours && !minutes) return 120;
  return Math.min(360, (hours ? Number(hours[1]) * 60 : 0) + (minutes ? Number(minutes[1]) : 0));
}

function requestDelayMinutes(text, fallback) {
  const normalized = text.toLowerCase();
  if (!/(\d+)\s*(?:hours?|hrs?|h)\b|(\d+)\s*(?:minutes?|mins?)\b/.test(normalized)) {
    return fallback;
  }
  return extractDelayMinutes(text);
}

function updateDelayLabel(minutes) {
  const hours = Math.floor(minutes / 60);
  const remainder = minutes % 60;
  delayLabel.textContent = `${hours ? `${hours}h ` : ""}${String(remainder).padStart(2, "0")}m`;
}

function renderConstraints(constraints) {
  const list = document.querySelector("#constraints-list");
  list.replaceChildren();
  constraints.forEach((constraint) => {
    const item = document.createElement("li");
    const mark = document.createElement("span");
    mark.className = "constraint-check";
    mark.textContent = constraint.protected ? "⌑" : "✓";
    const text = document.createElement("span");
    text.textContent = constraint.text;
    item.append(mark, text);
    list.append(item);
  });
}

function createPlanAction(action) {
  const article = document.createElement("article");
  article.className = "plan-action";
  article.dataset.actionId = action.id;

  const copy = document.createElement("div");
  copy.className = "plan-action-copy";
  const service = document.createElement("span");
  service.className = "service-label";
  service.textContent = action.service;
  const title = document.createElement("h3");
  title.textContent = action.title;
  const detail = document.createElement("p");
  detail.textContent = action.detail;
  const impact = document.createElement("p");
  impact.className = "action-impact";
  impact.textContent = action.impact;
  copy.append(service, title, detail);
  if (action.metadata) {
    const metadata = document.createElement("p");
    metadata.className = "action-metadata";
    metadata.textContent = action.metadata;
    copy.append(metadata);
  }
  copy.append(impact);

  const badge = document.createElement("span");
  badge.className = "action-status proposed";
  badge.textContent = "PROPOSED";
  const decisions = document.createElement("div");
  decisions.className = "action-decisions";
  const approve = document.createElement("button");
  approve.type = "button";
  approve.className = "action-approve";
  approve.textContent = "Approve";
  approve.dataset.decisionLabel = "Approve";
  approve.setAttribute("aria-label", `Approve and verify: ${action.title}`);
  approve.addEventListener("click", () => resolvePlanAction(action.id, true));
  const decline = document.createElement("button");
  decline.type = "button";
  decline.className = "action-decline";
  decline.textContent = "Decline";
  decline.dataset.decisionLabel = "Decline";
  decline.setAttribute("aria-label", `Decline and verify: ${action.title}`);
  decline.addEventListener("click", () => resolvePlanAction(action.id, false));
  const recover = document.createElement("button");
  recover.type = "button";
  recover.className = "action-recovery";
  recover.textContent = "Find recovery option";
  recover.hidden = true;
  recover.addEventListener("click", () => findRecoveryOptions(action.id, article));
  decisions.append(approve, decline, recover);
  article.append(copy, badge, decisions);
  return article;
}

function renderPlan(plan, constraints) {
  state.plan = plan;
  document.querySelector("#plan-summary").textContent = plan.summary;
  const priority = document.querySelector("#plan-priority");
  priority.hidden = !plan.priority;
  if (plan.priority) {
    priority.dataset.priority = plan.priority;
    priority.textContent = `${plan.priority.toUpperCase()} PICKUP RISK`;
  }
  renderConstraints(constraints);
  const blockers = document.querySelector("#plan-blockers");
  blockers.replaceChildren();
  (plan.blockers || []).forEach((message) => {
    const item = document.createElement("p");
    item.textContent = message;
    blockers.append(item);
  });
  blockers.hidden = !plan.blockers?.length;
  const actions = document.querySelector("#plan-actions");
  actions.replaceChildren();
  if (!plan.actions.length) {
    const empty = document.createElement("p");
    empty.className = "no-actions";
    empty.textContent = plan.status === "blocked"
      ? "No action was proposed. Review the blocker and compare eligible options before continuing."
      : "Nothing needs to change. Your evening plans stay as they are.";
    actions.append(empty);
    document.querySelector(".approval-required").textContent =
      plan.status === "blocked" ? "ACTION BLOCKED" : "NO CHANGES NEEDED";
  } else {
    plan.actions.forEach((action) => actions.append(createPlanAction(action)));
    document.querySelector(".approval-required").textContent = "DECIDE EACH ACTION";
  }
  renderImpactMap(plan);
  document.querySelector("#execution-summary").hidden = true;
  planSection.hidden = false;
  planSection.scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderPickupOptions(result) {
  state.pickupOptions = result;
  const panel = document.querySelector("#pickup-options-panel");
  const summary = document.querySelector("#pickup-risk-summary");
  const late = result.minutes_late;
  summary.textContent = late > 0
    ? `${result.commute} arrival is ${result.expected_arrival} — ${late} minutes after the ${result.deadline} pickup deadline.`
    : `${result.commute} arrival is ${result.expected_arrival}; the pickup deadline is ${result.deadline}.`;
  const cards = document.querySelector("#pickup-option-list");
  cards.replaceChildren();
  const eligible = result.options
    .filter((option) => option.eligible)
    .sort((a, b) => a.cost - b.cost || a.arrives_at.localeCompare(b.arrives_at));
  const recommendedId = result.recommendation?.option_id;
  const recommendation = document.querySelector("#pickup-recommendation");
  recommendation.hidden = !result.recommendation?.reason;
  document.querySelector("#pickup-recommendation-reason").textContent =
    result.recommendation?.reason || "";
  const tradeoff = document.querySelector("#pickup-tradeoff");
  tradeoff.hidden = !result.recommendation?.tradeoff;
  tradeoff.textContent = result.recommendation?.tradeoff || "";
  result.options.forEach((option) => {
    const label = document.createElement("label");
    const isRecommended = option.id === recommendedId;
    label.className = `pickup-option${option.eligible ? "" : " unavailable"}${isRecommended ? " recommended" : ""}`;
    const radio = document.createElement("input");
    radio.type = "radio";
    radio.name = "pickup-option";
    radio.value = option.id;
    radio.disabled = !option.eligible;
    radio.checked = isRecommended;
    const copy = document.createElement("span");
    copy.className = "pickup-option-copy";
    const title = document.createElement("strong");
    title.textContent = option.title;
    const detail = document.createElement("small");
    detail.textContent = option.detail;
    copy.append(title, detail);
    if (isRecommended) {
      const recommendationTag = document.createElement("span");
      recommendationTag.className = "pickup-option-tag";
      recommendationTag.textContent = "Ripple’s match";
      copy.append(recommendationTag);
    }
    const resultDetails = document.createElement("span");
    resultDetails.className = "pickup-option-result";
    const estimate = document.createElement("strong");
    estimate.textContent = option.cost === 0 ? "No cost" : `$${option.cost}`;
    const fit = document.createElement("small");
    if (!option.service_available) {
      fit.textContent = `${option.service} module offline`;
    } else if (!option.meets_deadline) {
      fit.textContent = `Arrives after ${result.deadline}`;
    } else if (!option.within_budget) {
      fit.textContent = `Over $${result.max_cost} budget`;
    } else {
      fit.textContent = `${option.arrives_at} · ${option.minutes_before_deadline} min buffer`;
    }
    resultDetails.append(estimate, fit);
    label.append(radio, copy, resultDetails);
    cards.append(label);
  });
  document.querySelector("#prepare-pickup-plan").disabled = !eligible.length;
  document.querySelector("#prepare-pickup-plan").textContent = eligible.length
    ? "Prepare approval request →"
    : "No eligible option";
  panel.hidden = false;
  panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

async function preparePickupPlan() {
  if (state.busy || !state.pickupOptions) return;
  const refreshed =
    document.querySelector("#pickup-deadline").value === state.pickupOptions.deadline &&
    Number(document.querySelector("#pickup-budget").value) === state.pickupOptions.max_cost &&
    document.querySelector("#pickup-priority").value === state.pickupOptions.recommendation?.objective &&
    Number(document.querySelector("#delay-minutes").value) === state.context?.pickup?.delay_minutes &&
    state.serviceAvailability.travel === state.context?.service_availability?.travel &&
    state.serviceAvailability.messaging === state.context?.service_availability?.messaging;
  if (!refreshed) {
    document.querySelector("#voice-note").textContent =
      "A deadline, budget, commute, or service setting changed. Find safe pickup options again to refresh the MCP comparison.";
    return;
  }
  const selected = document.querySelector('input[name="pickup-option"]:checked');
  if (!selected) {
    document.querySelector("#voice-note").textContent = "Choose an eligible pickup option first.";
    return;
  }
  setBusy(true, "Preparing the selected pickup action for your separate approval…");
  try {
    const plan = await callRippleTool("propose_recovery_plan", {
      delay_minutes: Number(document.querySelector("#delay-minutes").value) || 40,
      pickup_option_id: selected.value,
    });
    state.pickupOptions.planPrepared = Boolean(plan.actions.length);
    renderPlan(plan, state.context?.constraints || []);
    document.querySelector("#voice-note").textContent =
      "This is one proposed action. Nothing is sent or booked unless you approve it; the mock cannot verify a real handoff.";
  } catch (error) {
    document.querySelector("#voice-note").textContent = `Ripple couldn't prepare the pickup action: ${error.message}`;
  } finally {
    setBusy(false);
  }
}

async function buildRecoveryPlan() {
  if (state.busy) return;
  const request = document.querySelector("#request-input").value.trim();
  if (!request) {
    document.querySelector("#request-input").focus();
    document.querySelector("#voice-note").textContent = "Describe what changed so Ripple can build a plan.";
    return;
  }

  const delayInput = document.querySelector("#delay-minutes");
  const delay = Math.min(360, Math.max(0, requestDelayMinutes(request, Number(delayInput.value) || 0)));
  delayInput.value = String(delay);
  const scenario = inferScenario(request);
  selectScenario(scenario, false);
  updateDelayLabel(delay);
  setBusy(true, "One MCP call is preparing the scenario and gathering connected mock-service context…");
  planSection.hidden = true;
  resetImpactStatuses();
  try {
    await window.dominoMcp.connect();
    const context = await callRippleTool("prepare_recovery_context", {
      scenario,
      delay_minutes: delay,
      keep_dinner: document.querySelector("#keep-dinner").checked,
      delivery_provider_available: document.querySelector("#delivery-provider-available").checked,
      delivery_backup_available: document.querySelector("#delivery-backup-available").checked,
      dinner_option_index: Number(document.querySelector("#dinner-option").value),
      travel_available: state.serviceAvailability.travel,
      calendar_available: state.serviceAvailability.calendar,
      delivery_available: state.serviceAvailability.delivery,
      reservations_available: state.serviceAvailability.reservations,
      messaging_available: state.serviceAvailability.messaging,
    });
    state.context = context;
    const {
      flight,
      constraints,
      calendar,
      delivery,
      dinner_alternatives: dinnerAlternatives,
      service_availability: availability,
    } = context;
    state.serviceAvailability = { ...state.serviceAvailability, ...context.service_availability };
    updateImpact(
      "Travel",
      !scenario.startsWith("flight_")
        ? "SKIPPED"
        : availability.travel
          ? "READY"
          : "ERROR",
      !scenario.startsWith("flight_")
        ? "Not affected in this scenario"
        : flight
          ? `${flight.status} · arrival ${flight.updated_arrival}`
          : "Travel mock module is offline",
    );
    updateImpact(
      "Calendar",
      availability.calendar ? "READY" : "ERROR",
      calendar ? `${calendar.length} commitments checked` : "Calendar mock module is offline",
    );
    updateImpact(
      "Delivery",
      availability.delivery ? "READY" : "ERROR",
      delivery ? `${delivery.title} · ${delivery.window}` : "Delivery mock module is offline",
    );
    updateImpact(
      "Reservations",
      scenario === "flight_delay" || scenario === "meeting_overrun"
        ? availability.reservations
          ? "READY"
          : "ERROR"
        : "SKIPPED",
      scenario === "flight_delay" || scenario === "meeting_overrun"
        ? dinnerAlternatives
          ? `${dinnerAlternatives.length} alternatives available`
          : "Reservations mock module is offline"
        : "Not affected in this scenario",
    );
    updateImpact(
      "Messaging",
      availability.messaging ? "READY" : "ERROR",
      availability.messaging ? "Any message still requires your approval" : "Messaging mock module is offline",
    );
    renderServiceBoard();

    if (scenario === "pickup_risk") {
      updateImpact(
        "Travel",
        availability.travel ? "READY" : "ERROR",
        availability.travel ? `${context.pickup.commute} · arrival ${context.pickup.expected_arrival}` : "Transport mock module is offline",
      );
      updateImpact(
        "Calendar",
        availability.calendar ? "READY" : "ERROR",
        calendar ? `Protected pickup by ${context.pickup.deadline}` : "Calendar mock module is offline",
      );
      updateImpact("Delivery", "SKIPPED", "Not affected in this scenario");
      updateImpact("Reservations", "SKIPPED", "Not affected in this scenario");
      updateImpact(
        "Messaging",
        availability.messaging ? "READY" : "ERROR",
        availability.messaging ? "Backup contact details wait for your approval" : "Messaging mock module is offline",
      );
      const options = await callRippleTool("find_pickup_options", {
        deadline: document.querySelector("#pickup-deadline").value,
        max_cost: Number(document.querySelector("#pickup-budget").value),
        objective: document.querySelector("#pickup-priority").value,
      });
      if (options.constraints) state.context.constraints = options.constraints;
      renderPickupOptions(options);
      document.querySelector("#voice-note").textContent =
        "MCP checked the commute, pickup deadline, budget, and both mock options. Choose an eligible option to prepare its approval request.";
      return;
    }

    const plan = await callRippleTool("propose_recovery_plan", { delay_minutes: delay });
    renderPlan(plan, constraints);
    document.querySelector("#voice-note").textContent =
      "Plan generated from the service data shown in MCP activity. Nothing changes until you approve.";
    if ("speechSynthesis" in window) {
      window.speechSynthesis.cancel();
      window.speechSynthesis.speak(
        new SpeechSynthesisUtterance(`${plan.summary} Your plan is ready for review.`),
      );
    }
  } catch (error) {
    document.querySelector("#voice-note").textContent = `Ripple couldn't build the plan: ${error.message}`;
  } finally {
    setBusy(false);
  }
}

function renderImpactMap(plan) {
  const flow = document.querySelector("#impact-map-flow");
  flow.replaceChildren();
  if (!plan.actions.length) {
    const empty = document.createElement("p");
    empty.textContent = "No downstream action is needed for this scenario.";
    flow.append(empty);
    return;
  }
  plan.actions.forEach((action) => {
    const row = document.createElement("article");
    row.className = "impact-map-row";
    row.dataset.actionId = action.id;
    const source = document.createElement("span");
    source.className = "impact-map-source";
    const sourceDetails = {
      Transport: state.context?.pickup
        ? `${state.context.pickup.expected_arrival} commute · ${state.pickupOptions?.deadline || state.context.pickup.deadline} deadline`
        : "Pickup options MCP result",
      Travel: state.context?.flight
        ? `${state.context.flight.flight_id} · ${state.context.flight.status}`
        : "Travel MCP result",
      Calendar: `${state.context?.calendar?.length ?? 0} calendar commitments`,
      Deliveries: state.context?.delivery?.window || "Delivery MCP result",
      Reservations: `${state.context?.dinner_alternatives?.length ?? 0} reservation options`,
      Messaging: "User-approved messaging action",
    };
    source.textContent = sourceDetails[action.service] || `${action.service} tool result`;
    const connector = document.createElement("span");
    connector.className = "impact-map-connector";
    connector.textContent = "→";
    const affected = document.createElement("strong");
    affected.className = "impact-map-action";
    affected.textContent = action.title;
    const outcome = document.createElement("span");
    outcome.className = "impact-map-outcome";
    outcome.textContent = action.status && action.status !== "proposed"
      ? action.status.toUpperCase()
      : "AWAITING DECISION";
    if (action.status && action.status !== "proposed") outcome.dataset.status = action.status;
    row.append(source, connector, affected, outcome);
    flow.append(row);
  });
  (plan.blockers || []).forEach((message) => {
    const blocker = document.createElement("p");
    blocker.className = "impact-map-blocker";
    blocker.textContent = message;
    flow.append(blocker);
  });
}

function updateExecutionSummary() {
  const cards = [...document.querySelectorAll(".plan-action")];
  const summary = document.querySelector("#execution-summary");
  const resolved = cards.filter((card) => card.dataset.resolved === "true");
  if (!resolved.length) {
    summary.hidden = true;
    return;
  }
  const verified = resolved.filter((card) => card.dataset.status === "verified").length;
  const failed = resolved.filter((card) => card.dataset.status === "failed").length;
  const declined = resolved.filter((card) => card.dataset.status === "declined").length;
  const pending = cards.length - resolved.length;
  summary.textContent =
    `${verified} action${verified === 1 ? "" : "s"} verified · ${failed} failed · ${declined} declined · ${pending} awaiting your decision. Each result was checked separately.`;
  summary.hidden = false;
}

async function resolvePlanAction(actionId, approved) {
  if (!state.plan || state.busy) return;
  const article = document.querySelector(`.plan-action[data-action-id="${CSS.escape(actionId)}"]`);
  if (!article || article.dataset.resolved === "true") return;
  const controls = article.querySelectorAll(".action-decisions button");
  const badge = article.querySelector(".action-status");
  const impact = article.querySelector(".action-impact");
  controls.forEach((button) => {
    button.disabled = true;
  });
  badge.textContent = approved ? "APPROVING…" : "DECLINING…";
  setBusy(true, `${approved ? "Approving" : "Declining"} this action, then verifying it with MCP…`);
  try {
    let execution;
    if (!article.dataset.executionStatus) {
      execution = await callRippleTool("execute_approved_action", {
        plan_id: state.plan.plan_id,
        action_id: actionId,
        user_approved: approved,
      });
      article.dataset.executionStatus = execution.status;
    }
    const verification = await callRippleTool("verify_action_status", {
      plan_id: state.plan.plan_id,
      action_id: actionId,
    });
    article.dataset.resolved = "true";
    article.dataset.status = verification.status;
    const planAction = state.plan.actions.find((action) => action.id === actionId);
    if (planAction) planAction.status = verification.status;
    badge.textContent = verification.status.toUpperCase();
    badge.className = `action-status ${verification.verified ? "verified" : verification.status}`;
    impact.textContent = verification.evidence || execution?.message || "The action status was checked.";
    const recoveryButton = article.querySelector(".action-recovery");
    recoveryButton.hidden = !(
      verification.status === "failed" &&
      actionId === "delivery-reschedule" &&
      state.tools.has("find_recovery_options")
    );
    const mapOutcome = document.querySelector(`.impact-map-row[data-action-id="${CSS.escape(actionId)}"] .impact-map-outcome`);
    if (mapOutcome) {
      mapOutcome.textContent = verification.status.toUpperCase();
      mapOutcome.dataset.status = verification.status;
    }
    updateExecutionSummary();
    document.querySelector("#voice-note").textContent =
      `${approved ? "Approved" : "Declined"} this action and checked its result. You can now decide on each remaining action separately.`;
  } catch (error) {
    controls.forEach((button) => {
      button.textContent = article.dataset.executionStatus ? "Retry verification" : button.dataset.decisionLabel;
      button.disabled = false;
    });
    badge.textContent = article.dataset.executionStatus ? "CHECK FAILED" : "NOT VERIFIED";
    badge.className = "action-status failed";
    impact.textContent = article.dataset.executionStatus
      ? `The decision was recorded, but verification failed. Use Retry verification; it will not execute the action again. (${error.message})`
      : `Ripple could not confirm whether the action was recorded. Retry cautiously: ${error.message}`;
    document.querySelector("#voice-note").textContent =
      `This action remains unresolved because verification failed: ${error.message}`;
  } finally {
    setBusy(false);
    if (article.dataset.resolved === "true") {
      controls.forEach((button) => {
        if (!button.classList.contains("action-recovery")) button.disabled = true;
      });
    }
  }
}

async function findRecoveryOptions(actionId, failedArticle) {
  if (!state.plan || state.busy) return;
  if (!state.tools.has("find_recovery_options")) {
    failedArticle.querySelector(".action-impact").textContent =
      "No fallback tool was discovered from this MCP server.";
    return;
  }
  const button = failedArticle.querySelector(".action-recovery");
  button.disabled = true;
  setBusy(true, "Asking the discovered recovery-options tool for a real available fallback…");
  try {
    const result = await callRippleTool("find_recovery_options", {
      plan_id: state.plan.plan_id,
      action_id: actionId,
    });
    if (!result.options.length) {
      failedArticle.querySelector(".action-impact").textContent = result.message;
      button.hidden = true;
      return;
    }
    const actions = document.querySelector("#plan-actions");
    result.options.forEach((action) => {
      state.plan.actions.push(action);
      actions.append(createPlanAction(action));
    });
    renderImpactMap(state.plan);
    failedArticle.querySelector(".action-impact").textContent =
      "A viable backup was returned by MCP and added as a separate proposal. Review and approve or decline it independently.";
    button.hidden = true;
    updateExecutionSummary();
  } catch (error) {
    failedArticle.querySelector(".action-impact").textContent =
      `Could not retrieve a recovery option from MCP: ${error.message}`;
    button.disabled = false;
  } finally {
    setBusy(false);
  }
}

function startVoiceInput() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  const note = document.querySelector("#voice-note");
  if (!SpeechRecognition) {
    note.textContent = "Voice input is not available in this browser. Type your request instead.";
    return;
  }
  const recognition = new SpeechRecognition();
  recognition.lang = navigator.language || "en-US";
  recognition.interimResults = false;
  recognition.maxAlternatives = 1;
  recognition.onstart = () => {
    note.textContent = "Listening… say what changed and what you want protected.";
    document.querySelector("#voice-input").classList.add("listening");
  };
  recognition.onresult = (event) => {
    document.querySelector("#request-input").value = event.results[0][0].transcript;
    note.textContent = "Got it. Review or edit your request, then ask Ripple to find the effects.";
  };
  recognition.onerror = (event) => {
    note.textContent = `Voice input stopped (${event.error}). You can type your request instead.`;
  };
  recognition.onend = () => document.querySelector("#voice-input").classList.remove("listening");
  recognition.start();
}

async function resetScenario() {
  if (state.busy) return;
  setBusy(true, "Restoring the original mock scenario…");
  try {
    await window.dominoMcp.connect();
    await callRippleTool("reset_demo_scenario");
    state.plan = null;
    state.context = null;
    selectScenario("pickup_risk");
    document.querySelector("#delay-minutes").value = "40";
    document.querySelector("#pickup-deadline").value = "6:00 PM";
    document.querySelector("#pickup-budget").value = "25";
    document.querySelector("#dinner-option").value = "0";
    document.querySelector("#keep-dinner").checked = true;
    document.querySelector("#delivery-provider-available").checked = true;
    document.querySelector("#delivery-backup-available").checked = true;
    state.serviceAvailability = {
      travel: true,
      calendar: true,
      delivery: true,
      reservations: true,
      messaging: true,
    };
    renderServiceBoard();
    planSection.hidden = true;
    document.querySelector("#execution-summary").hidden = true;
    document.querySelector("#request-input").value = SCENARIOS.pickup_risk.request;
    state.pickupOptions = null;
    updateDelayLabel(40);
    resetImpactStatuses();
    document.querySelector("#voice-note").textContent = "Demo reset. Nothing real is connected.";
  } catch (error) {
    document.querySelector("#voice-note").textContent = `Could not reset the demo: ${error.message}`;
  } finally {
    setBusy(false);
  }
}

function applyTheme(theme) {
  const isLight = theme === "light";
  document.documentElement.dataset.theme = isLight ? "light" : "dark";
  document.querySelector('meta[name="theme-color"]').content = isLight ? "#f4f6f4" : "#111512";
  themeToggle.innerHTML = isLight ? "◐ <span>Dark mode</span>" : "☼ <span>Light mode</span>";
  themeToggle.setAttribute("aria-label", `Switch to ${isLight ? "dark" : "light"} theme`);
  try {
    localStorage.setItem("ripple-theme-v1", isLight ? "light" : "dark");
  } catch (error) {
    document.querySelector("#voice-note").textContent = "Theme changed, but your browser could not save the preference.";
  }
}

themeToggle.addEventListener("click", () => {
  applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
});
buildButton.addEventListener("click", buildRecoveryPlan);
document.querySelector("#prepare-pickup-plan").addEventListener("click", preparePickupPlan);
document.querySelector("#voice-input").addEventListener("click", startVoiceInput);
document.querySelector("#reset-scenario").addEventListener("click", resetScenario);
document.querySelectorAll(".scenario-choice").forEach((button) => {
  button.addEventListener("click", () => selectScenario(button.dataset.scenario));
});
document.querySelector("#request-input").addEventListener("input", (event) => {
  const delay = requestDelayMinutes(event.target.value, Number(document.querySelector("#delay-minutes").value) || 0);
  updateDelayLabel(delay);
  if (inferScenario(event.target.value) !== state.scenario) {
    selectScenario(inferScenario(event.target.value), false);
  }
});
document.querySelector("#delay-minutes").addEventListener("input", (event) => {
  const minutes = Math.min(360, Math.max(0, Number(event.target.value) || 0));
  updateDelayLabel(minutes);
});
document.querySelector("#keep-dinner").addEventListener("change", updateConstraintPreview);
document.querySelector("#pickup-deadline").addEventListener("change", updateConstraintPreview);
document.querySelector("#pickup-budget").addEventListener("change", updateConstraintPreview);
document.querySelector("#pickup-priority").addEventListener("change", updateConstraintPreview);
document.querySelector("#request-input").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) buildRecoveryPlan();
});

window.dominoMcp.onStatusChange((ready) => {
  const button = document.querySelector("#mcp-status");
  button.classList.toggle("connected", ready);
  button.classList.toggle("disconnected", !ready);
  document.querySelector("#mcp-status-label").textContent = ready ? "MCP · CONNECTED" : "MCP · RECONNECT";
  if (!ready) document.querySelector("#control-server-status").textContent = "MCP SERVER · OFFLINE";
});

async function initialize() {
  applyTheme(document.documentElement.dataset.theme === "light" ? "light" : "dark");
  selectScenario("pickup_risk", false);
  updateConstraintPreview();
  setBusy(true, "Connecting to the Ripple MCP server and discovering tools…");
  try {
    await discoverMcpTools();
  } catch (error) {
    document.querySelector("#voice-note").textContent =
      `Couldn't connect to Ripple MCP (${error.message}). Keep the server running, then reload.`;
  } finally {
    setBusy(false);
  }
}

async function discoverMcpTools() {
  await window.dominoMcp.connect();
  const tools = await window.dominoMcp.listTools();
  state.tools = new Set(tools.map((tool) => tool.name));
  state.toolCatalog = new Map(tools.map((tool) => [tool.name, tool]));
  renderServiceBoard();
  logActivity("tools/list", {}, {
    count: tools.length,
    tools: tools.map((tool) => tool.name),
  });
  const missing = REQUIRED_TOOLS.filter((tool) => !state.tools.has(tool));
  if (missing.length) {
    throw new Error(`Ripple MCP server is missing required tools: ${missing.join(", ")}.`);
  }
  document.querySelector("#voice-note").textContent =
    `Connected. Discovered ${tools.length} Ripple MCP tools; ready to simulate the disruption.`;
}

document.querySelector("#mcp-status").addEventListener("click", async () => {
  if (state.busy || window.dominoMcp.ready) return;
  setBusy(true, "Reconnecting to the Ripple MCP server…");
  try {
    await discoverMcpTools();
  } catch (error) {
    document.querySelector("#voice-note").textContent =
      `Couldn't reconnect to Ripple MCP (${error.message}). Keep the server running, then try again.`;
  } finally {
    setBusy(false);
  }
});

initialize();

const ACTIVITY_STORAGE_KEY = "ripple-mcp-activity-v1";
const activityFeed = document.querySelector("#activity-feed");
const countLabel = document.querySelector("#logs-count");
const feedback = document.querySelector("#logs-feedback");

function readActivity() {
  const saved = localStorage.getItem(ACTIVITY_STORAGE_KEY);
  if (!saved) return [];
  const entries = JSON.parse(saved);
  if (!Array.isArray(entries)) throw new Error("Saved MCP activity has an invalid format.");
  return entries;
}

function renderEntry(entry) {
  const article = document.createElement("article");
  article.className = `activity-entry${entry.failed ? " failed" : ""}`;

  const heading = document.createElement("div");
  heading.className = "activity-entry-heading";
  const name = document.createElement("strong");
  name.textContent = entry.toolName || "Unknown MCP tool";
  const label = document.createElement("span");
  label.textContent = entry.failed ? "ERROR" : entry.toolName === "tools/list" ? "DISCOVERY" : "MCP TOOL";
  heading.append(name, label);

  const meta = document.createElement("div");
  meta.className = "activity-entry-meta";
  const purpose = document.createElement("p");
  purpose.className = "activity-purpose";
  purpose.textContent = entry.purpose || "MCP tool request and returned result.";
  const timestamp = document.createElement("time");
  timestamp.dateTime = entry.timestamp || "";
  const date = new Date(entry.timestamp);
  timestamp.textContent = Number.isNaN(date.getTime()) ? "Time unavailable" : date.toLocaleString();
  meta.append(purpose, timestamp);

  const details = document.createElement("details");
  const summary = document.createElement("summary");
  summary.textContent = entry.failed ? "Inspect error details" : "Inspect request and result";
  const content = document.createElement("pre");
  content.textContent = JSON.stringify(
    { arguments: entry.arguments ?? {}, result: entry.result ?? null },
    null,
    2,
  );
  details.append(summary, content);
  article.append(heading, meta, details);
  return article;
}

function renderLogs() {
  try {
    const entries = readActivity();
    activityFeed.replaceChildren();
    if (!entries.length) {
      const empty = document.createElement("div");
      empty.className = "empty-activity";
      const icon = document.createElement("span");
      icon.textContent = "◌";
      const message = document.createElement("p");
      message.textContent =
        "No MCP activity yet. Use Ripple to build a plan; requests and results will appear here.";
      empty.append(icon, message);
      activityFeed.append(empty);
    } else {
      [...entries].reverse().forEach((entry) => activityFeed.append(renderEntry(entry)));
    }
    countLabel.textContent = `${entries.length} recorded request${entries.length === 1 ? "" : "s"}`;
    feedback.textContent = "";
  } catch (error) {
    countLabel.textContent = "Could not load saved activity.";
    feedback.textContent = `Ripple Logs couldn't read saved activity: ${error.message}`;
  }
}

function applyTheme(theme) {
  const isLight = theme === "light";
  document.documentElement.dataset.theme = isLight ? "light" : "dark";
  document.querySelector('meta[name="theme-color"]').content = isLight ? "#f4f6f4" : "#111512";
  const button = document.querySelector("#logs-theme-toggle");
  button.innerHTML = isLight ? "◐ <span>Dark mode</span>" : "☼ <span>Light mode</span>";
  button.setAttribute("aria-label", `Switch to ${isLight ? "dark" : "light"} theme`);
  try {
    localStorage.setItem("ripple-theme-v1", isLight ? "light" : "dark");
  } catch (error) {
    feedback.textContent = `Theme changed, but this browser could not save it: ${error.message}`;
  }
}

document.querySelector("#clear-logs").addEventListener("click", () => {
  try {
    localStorage.removeItem(ACTIVITY_STORAGE_KEY);
    renderLogs();
    feedback.textContent = "MCP activity logs cleared.";
  } catch (error) {
    feedback.textContent = `Could not clear MCP logs: ${error.message}`;
  }
});

document.querySelector("#logs-theme-toggle").addEventListener("click", () => {
  applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
});

window.addEventListener("storage", (event) => {
  if (event.key === ACTIVITY_STORAGE_KEY) renderLogs();
});

renderLogs();

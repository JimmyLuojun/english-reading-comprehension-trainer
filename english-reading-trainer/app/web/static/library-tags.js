(() => {
  "use strict";

  const pickerSelector = "[data-tag-picker]";

  function normalizedKey(value) {
    return value.trim().toLocaleLowerCase();
  }

  function tagOptions(picker) {
    return Array.from(picker.querySelectorAll("[data-tag-option]"));
  }

  function selectedTags(picker) {
    return tagOptions(picker)
      .filter((option) => option.checked)
      .map((option) => option.value.trim())
      .filter(Boolean);
  }

  function renderSummary(picker, tags) {
    const summary = picker.querySelector("[data-tag-summary]");
    if (!summary) return;
    summary.replaceChildren();
    if (!tags.length) {
      const placeholder = document.createElement("span");
      placeholder.className = "library-tag-placeholder";
      placeholder.textContent = "Select tags";
      summary.append(placeholder);
      return;
    }
    for (const tag of tags) {
      const chip = document.createElement("span");
      chip.className = "library-tag-chip";
      chip.textContent = tag;
      summary.append(chip);
    }
  }

  function syncPicker(picker) {
    const tags = selectedTags(picker);
    const value = picker.querySelector("[data-tag-value]");
    if (value) value.value = tags.join(", ");
    renderSummary(picker, tags);
    const empty = picker.querySelector("[data-tag-empty]");
    if (empty) empty.hidden = tagOptions(picker).length > 0;
  }

  function createTagOption(picker, tag) {
    const options = picker.querySelector("[data-tag-options]");
    if (!options) return null;
    const label = document.createElement("label");
    label.className = "library-tag-option";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.value = tag;
    checkbox.checked = true;
    checkbox.dataset.tagOption = "";
    const text = document.createElement("span");
    text.textContent = tag;
    label.append(checkbox, text);
    options.append(label);
    return checkbox;
  }

  function addTags(picker) {
    const input = picker.querySelector("[data-tag-new]");
    if (!input) return;
    const candidates = input.value
      .split(",")
      .map((tag) => tag.trim())
      .filter(Boolean);
    const invalid = candidates.find((tag) => tag.length > 60);
    input.setCustomValidity(invalid ? "Tags must be 60 characters or fewer." : "");
    if (invalid) {
      input.reportValidity();
      return;
    }
    for (const candidate of candidates) {
      const key = normalizedKey(candidate);
      const existing = tagOptions(picker).find(
        (option) => normalizedKey(option.value) === key,
      );
      if (existing) existing.checked = true;
      else createTagOption(picker, candidate);
    }
    input.value = "";
    syncPicker(picker);
    input.focus();
  }

  document.addEventListener("change", (event) => {
    const option = event.target.closest?.("[data-tag-option]");
    if (!option) return;
    const picker = option.closest(pickerSelector);
    if (picker) syncPicker(picker);
  });

  document.addEventListener("click", (event) => {
    const button = event.target.closest?.("[data-tag-add]");
    if (!button) return;
    const picker = button.closest(pickerSelector);
    if (picker) addTags(picker);
  });

  document.addEventListener("keydown", (event) => {
    const input = event.target.closest?.("[data-tag-new]");
    if (!input || event.key !== "Enter") return;
    event.preventDefault();
    const picker = input.closest(pickerSelector);
    if (picker) addTags(picker);
  });

  for (const picker of document.querySelectorAll(pickerSelector)) {
    syncPicker(picker);
  }
})();

(function () {
  const nav = document.querySelector("#nav-dialog");
  const openNav = document.querySelector("[data-open-nav]");
  if (nav && openNav) {
    openNav.addEventListener("click", function () {
      nav.showModal();
    });
    nav.addEventListener("click", function (event) {
      if (event.target === nav) nav.close();
    });
    nav.querySelectorAll("a, .close-nav").forEach(function (el) {
      el.addEventListener("click", function () {
        nav.close();
      });
    });
  }

  const lightbox = document.querySelector("#lightbox");
  const shots = Array.from(document.querySelectorAll(".shot"));
  if (lightbox && shots.length) {
    const img = lightbox.querySelector("img");
    const cap = lightbox.querySelector("figcaption");
    let index = 0;

    function show(i) {
      index = (i + shots.length) % shots.length;
      const shot = shots[index];
      const source = shot.querySelector("img");
      img.src = source.currentSrc || source.src;
      img.alt = source.alt;
      img.width = source.width;
      img.height = source.height;
      const caption = shot.parentElement.querySelector("figcaption");
      cap.textContent = caption ? caption.textContent : source.alt;
      if (!lightbox.open) lightbox.showModal();
    }

    shots.forEach(function (shot, i) {
      shot.addEventListener("click", function () {
        show(i);
      });
    });

    lightbox.addEventListener("click", function (event) {
      if (event.target === lightbox) lightbox.close();
    });
    lightbox.querySelector("[data-prev]").addEventListener("click", function () {
      show(index - 1);
    });
    lightbox.querySelector("[data-next]").addEventListener("click", function () {
      show(index + 1);
    });
    lightbox.querySelector("[data-close]").addEventListener("click", function () {
      lightbox.close();
    });
  }

  document.querySelectorAll("[data-form]").forEach(function (form) {
    const status = form.querySelector(".form-status");
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      const trap = form.querySelector(".honeypot input, .honeypot textarea");
      if (trap && trap.value) {
        status.dataset.state = "error";
        status.textContent = "That did not go through.";
        return;
      }
      if (!form.checkValidity()) {
        form.reportValidity();
        return;
      }
      const data = new FormData(form);
      const topic = data.get("topic") || "note";
      const name = data.get("name") || "";
      status.dataset.state = "ok";
      status.textContent =
        "Saved in this browser only. This preview does not send mail. Write " +
        (topic === "support" || topic === "service"
          ? "support@olamiccutlery.com"
          : "team@olamiccutlery.com") +
        (name ? " and mention " + name : "") +
        ".";
      form.reset();
    });
  });

  const filterRoot = document.querySelector("[data-filter-root]");
  if (filterRoot) {
    const cards = Array.from(filterRoot.querySelectorAll("[data-tags]"));
    const search = filterRoot.querySelector('input[type="search"]');
    const chips = Array.from(filterRoot.querySelectorAll("[data-chip]"));
    let chip = "all";

    const empty = filterRoot.querySelector("[data-empty]");

    function apply() {
      const q = (search && search.value ? search.value : "").trim().toLowerCase();
      let shown = 0;
      cards.forEach(function (card) {
        const tags = card.dataset.tags || "";
        const text = card.textContent.toLowerCase();
        const chipOk = chip === "all" || tags.split(" ").includes(chip);
        const textOk = !q || text.includes(q);
        const ok = chipOk && textOk;
        card.hidden = !ok;
        if (ok) shown += 1;
      });
      if (empty) empty.hidden = shown !== 0;
    }

    chips.forEach(function (button) {
      button.addEventListener("click", function () {
        chip = button.dataset.chip;
        chips.forEach(function (other) {
          other.setAttribute("aria-pressed", other === button ? "true" : "false");
        });
        apply();
      });
    });
    if (search) search.addEventListener("input", apply);
  }

  const assistant = document.querySelector("#assistant");
  const dataNode = document.querySelector("#assistant-data");
  if (assistant && dataNode) {
    const data = JSON.parse(dataNode.textContent);
    const model = assistant.querySelector("[name='model']");
    const blade = assistant.querySelector("[name='blade']");
    const steel = assistant.querySelector("[name='steel']");
    const finish = assistant.querySelector("[name='finish']");
    const note = assistant.querySelector("[name='note']");
    const summary = assistant.querySelector("[data-summary]");

    function fill(select, values, current) {
      const keep = current && values.includes(current) ? current : values[0];
      select.replaceChildren();
      values.forEach(function (value) {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = value;
        if (value === keep) option.selected = true;
        select.append(option);
      });
    }

    function currentModel() {
      return data.models.find(function (item) {
        return item.name === model.value;
      });
    }

    function render() {
      const item = currentModel();
      if (!item) return;
      fill(blade, item.blades, blade.value);
      fill(steel, item.steels, steel.value);
      const lines = [
        item.name,
        blade.value + " blade",
        steel.value,
        finish.value,
        item.lock + ", " + item.open
      ];
      summary.replaceChildren();
      lines.forEach(function (line, i) {
        const p = document.createElement("p");
        if (i === 0) p.className = "serif";
        p.textContent = line;
        if (i === 0) p.style.fontSize = "1.8rem";
        summary.append(p);
      });
    }

    fill(model, data.models.map(function (item) { return item.name; }), data.models[0].name);
    fill(finish, data.finishes, data.finishes[0]);
    model.addEventListener("change", render);
    blade.addEventListener("change", render);
    steel.addEventListener("change", render);
    finish.addEventListener("change", render);
    render();

    const request = assistant.querySelector("[data-request]");
    if (request) {
      request.addEventListener("click", function () {
        const item = currentModel();
        const text = [
          item.name,
          blade.value,
          steel.value,
          finish.value,
          note.value
        ].filter(Boolean).join(". ");
        const field = document.querySelector("#build-message");
        if (field) {
          field.value = text;
          field.focus();
        }
      });
    }
  }
})();

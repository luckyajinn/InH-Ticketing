/*
 * InH-Ticketing: small progressive enhancements. Every page works without
 * this file; it only saves clicks and adds gentle motion.
 *
 * Loaded in <head> without "defer" so the "js" class is on <html> before
 * the first paint: entrance animations (gated behind .js in app.css) then
 * never flash visible-hidden-visible. The rest waits for the DOM.
 */
(function () {
  "use strict";
  document.documentElement.classList.add("js");

  function ready(fn) {
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", fn);
    else fn();
  }

  ready(function () {
    // A reply being typed survives the side panel saving (which reloads the
    // page): it's set aside just before the save and put back afterwards.
    var DRAFT_KEY = "inh-draft:" + window.location.pathname;
    var composerText = document.getElementById("composer-text");

    function keepDraft() {
      if (!composerText || !composerText.value.trim()) return;
      var mode = document.querySelector("input[name=visibility]:checked");
      try {
        window.sessionStorage.setItem(DRAFT_KEY, JSON.stringify({
          body: composerText.value, visibility: mode ? mode.value : "public"
        }));
      } catch (e) { /* private browsing: nothing to keep it in */ }
    }

    if (composerText) {
      var saved = null;
      try {
        saved = JSON.parse(window.sessionStorage.getItem(DRAFT_KEY) || "null");
        window.sessionStorage.removeItem(DRAFT_KEY);
      } catch (e) { saved = null; }
      if (saved && saved.body && !composerText.value.trim()) {
        composerText.value = saved.body;
        var radio = document.querySelector('input[name=visibility][value="' + (saved.visibility === "internal" ? "internal" : "public") + '"]');
        if (radio && !radio.checked) {
          radio.checked = true;
          radio.dispatchEvent(new Event("change", { bubbles: true }));
        }
      }
    }

    // Forms marked data-autosubmit save as soon as a field changes
    // (the side panel on a ticket). Without JS, a Save button is shown instead.
    document.querySelectorAll("form[data-autosubmit]").forEach(function (form) {
      form.addEventListener("submit", keepDraft); // "Assign to me" and the no-JS Save button
      form.addEventListener("change", function () {
        keepDraft();
        form.classList.add("is-saving");
        var hint = form.querySelector(".props-hint");
        if (hint) hint.textContent = "Saving\u2026";
        if (form.requestSubmit) form.requestSubmit(); else form.submit();
      });
    });

    // Whole queue rows are clickable; the subject link stays the real link.
    document.querySelectorAll("tr[data-href]").forEach(function (row) {
      row.addEventListener("click", function (event) {
        if (event.target.closest("a, button, input, select, label")) return;
        window.location.href = row.getAttribute("data-href");
      });
    });

    // Show the names of chosen files next to a file input.
    document.querySelectorAll("input[type=file][data-file-list]").forEach(function (input) {
      var target = document.getElementById(input.getAttribute("data-file-list"));
      if (!target) return;
      input.addEventListener("change", function () {
        var names = Array.prototype.map.call(input.files, function (f) { return f.name; });
        target.textContent = names.length ? "Attached: " + names.join(", ") : "";
      });
    });

    // Drag and drop onto a dropzone label fills its file input. A counter
    // keeps the highlight steady while the pointer crosses child elements.
    document.querySelectorAll(".dropzone").forEach(function (zone) {
      var input = zone.querySelector("input[type=file]");
      if (!input) return;
      var depth = 0;
      zone.addEventListener("dragenter", function (e) { e.preventDefault(); depth += 1; zone.classList.add("is-over"); });
      zone.addEventListener("dragover", function (e) { e.preventDefault(); });
      zone.addEventListener("dragleave", function () {
        depth = Math.max(0, depth - 1);
        if (!depth) zone.classList.remove("is-over");
      });
      zone.addEventListener("drop", function (e) {
        e.preventDefault();
        depth = 0;
        zone.classList.remove("is-over");
        if (e.dataTransfer && e.dataTransfer.files.length) {
          input.files = e.dataTransfer.files;
          input.dispatchEvent(new Event("change", { bubbles: true }));
        }
      });
    });

    // The composer's placeholder follows the Public / Internal choice.
    document.querySelectorAll(".composer").forEach(function (composer) {
      var text = composer.querySelector("textarea");
      if (!text) return;
      composer.querySelectorAll("input[name=visibility]").forEach(function (radio) {
        radio.addEventListener("change", function () {
          var attr = radio.value === "internal" ? "data-placeholder-internal" : "data-placeholder-public";
          text.placeholder = text.getAttribute(attr) || "";
        });
      });
    });

    // Reports: a tooltip for each column of the chart, on hover or keyboard
    // focus. It only repeats what the table under the chart already says.
    document.querySelectorAll("[data-chart]").forEach(function (chart) {
      var tip = chart.querySelector(".chart-tip");
      if (!tip) return;
      function show(mark) {
        tip.textContent = "";
        var title = document.createElement("p");
        title.className = "chart-tip-title";
        title.textContent = mark.getAttribute("data-tip-title") || "";
        tip.appendChild(title);
        (mark.getAttribute("data-tip-rows") || "").split(";").forEach(function (row) {
          var parts = row.split("|");
          if (parts.length < 3) return;
          var line = document.createElement("p");
          line.className = "chart-tip-row";
          var key = document.createElement("span");
          key.className = "chart-tip-key key-" + parts[2];
          var value = document.createElement("strong");
          value.textContent = parts[1];
          var name = document.createElement("span");
          name.textContent = parts[0];
          line.appendChild(key);
          line.appendChild(value);
          line.appendChild(name);
          tip.appendChild(line);
        });
        tip.hidden = false;
        var box = chart.getBoundingClientRect();
        var hit = mark.getBoundingClientRect();
        var top = hit.bottom;
        mark.parentNode.querySelectorAll("path").forEach(function (path) {
          top = Math.min(top, path.getBoundingClientRect().top);
        });
        var left = hit.left - box.left + hit.width / 2 - tip.offsetWidth / 2;
        tip.style.left = Math.max(0, Math.min(left, box.width - tip.offsetWidth)) + "px";
        tip.style.top = Math.max(0, top - box.top - tip.offsetHeight - 8) + "px";
      }
      function hide() { tip.hidden = true; }
      chart.querySelectorAll("[data-tip-title]").forEach(function (mark) {
        mark.addEventListener("pointerenter", function () { show(mark); });
        mark.addEventListener("focus", function () { show(mark); });
        mark.addEventListener("pointerleave", hide);
        mark.addEventListener("blur", hide);
      });
    });

    // "Common requests" on the New request form: a chosen one is the subject.
    // The subject box greys out (a disabled field isn't sent) and a note says
    // what's typed there won't be used; what was typed stays, in case they
    // choose "None" again. Choosing one also fills in its category. Without
    // JS the server uses the chosen one as the subject on submit.
    document.querySelectorAll("select[data-subject-pick]").forEach(function (pick) {
      var form = pick.form;
      var subject = form && form.elements.subject;
      var category = form && form.elements.category;
      var note = form && form.querySelector("[data-subject-override]");
      if (!subject) return;
      var field = subject.closest(".field");

      function update(chosenNow) {
        var option = pick.options[pick.selectedIndex];
        var picked = !!(option && option.value);
        subject.disabled = picked;
        subject.placeholder = picked ? option.textContent.trim() : "";
        if (field) field.classList.toggle("is-overridden", picked);
        if (note) note.textContent = picked ? note.getAttribute("data-text") : "";
        var group = option && option.parentElement;
        if (picked && chosenNow && category && group && group.getAttribute("data-category")) {
          category.value = group.getAttribute("data-category");
        }
      }
      pick.addEventListener("change", function () { update(true); });
      // Also when the browser puts back a chosen one (Back button, reload).
      window.addEventListener("pageshow", function () { update(false); });
      update(false);
    });

    // "This might include a password" (tickets/password_guard.py). Before a
    // form is sent, ask the server whether its text looks like it holds a
    // password, so chosen files stay attached if it does. If the check can't
    // run, the form is sent as usual and the server checks it on arrival.
    document.querySelectorAll("form[data-password-check]").forEach(function (form) {
      var panel = form.querySelector("[data-password-warning]");
      var hintList = form.querySelector("[data-password-hints]");
      var ack = form.querySelector("input[name=password_ack]");
      var warned = form.querySelector("input[name=password_warned]");
      var names = (form.getAttribute("data-password-fields") || "").split(" ");
      if (!panel || !window.fetch || !window.FormData) return;
      var cleared = null; // the text the server last said was fine
      var busy = false;

      // Disabled fields aren't sent (a subject replaced by a common request), so they aren't checked.
      function currentText() {
        return names.map(function (name) {
          var field = form.elements[name];
          return field && !field.disabled ? field.value : "";
        }).join("\u0000");
      }

      function send(submitter) {
        busy = false;
        cleared = currentText();
        if (form.requestSubmit) form.requestSubmit(submitter || undefined); else form.submit();
      }

      function warn(hints) {
        busy = false;
        hintList.textContent = "";
        hints.forEach(function (hint) {
          var item = document.createElement("li");
          item.textContent = hint;
          hintList.appendChild(item);
        });
        if (warned) warned.value = "on";
        panel.hidden = false;
        panel.focus();
      }

      form.addEventListener("submit", function (event) {
        if ((ack && ack.checked) || cleared === currentText()) return;
        event.preventDefault();
        if (busy) return;
        busy = true;
        // The button that was clicked, so "Send and resolve" still resolves.
        var submitter = event.submitter || null;
        var data = new FormData();
        data.append("csrfmiddlewaretoken", form.elements.csrfmiddlewaretoken.value);
        names.forEach(function (name) {
          var field = form.elements[name];
          if (field && !field.disabled) data.append(name, field.value);
        });
        fetch(form.getAttribute("data-password-check"), { method: "POST", body: data, credentials: "same-origin" })
          .then(function (response) {
            if (!response.ok) throw new Error("check failed");
            return response.json();
          })
          .then(function (result) {
            if (result.found) warn(result.hints || []); else send(submitter);
          })
          .catch(function () { send(submitter); });
      });
    });

    // Sending: once a form really goes (nothing above stopped it), show it on
    // the button that was pressed and ignore further clicks, so a double click
    // can't send a request or reply twice. This runs after the password check,
    // which stops the first submit while it asks the server.
    document.querySelectorAll("form[method=post]:not([data-autosubmit])").forEach(function (form) {
      form.addEventListener("submit", function (event) {
        if (event.defaultPrevented) return;
        if (form.getAttribute("aria-busy") === "true") {
          event.preventDefault();
          return;
        }
        form.setAttribute("aria-busy", "true");
        var button = event.submitter || form.querySelector("button[type=submit]");
        if (button) button.classList.add("is-sending");
      });
    });

    // Coming back with the Back button shows the form ready again.
    window.addEventListener("pageshow", function (event) {
      if (!event.persisted) return;
      document.querySelectorAll("form[aria-busy=true]").forEach(function (form) {
        form.removeAttribute("aria-busy");
        form.querySelectorAll(".is-sending").forEach(function (button) { button.classList.remove("is-sending"); });
      });
    });
  });
})();

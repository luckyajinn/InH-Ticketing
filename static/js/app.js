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
    // Forms marked data-autosubmit save as soon as a field changes
    // (the side panel on a ticket). Without JS, a Save button is shown instead.
    document.querySelectorAll("form[data-autosubmit]").forEach(function (form) {
      form.addEventListener("change", function () {
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

    // "Common requests" on the New request form fill in the subject and the
    // category straight away. Without JS the server does the same on submit.
    document.querySelectorAll("select[data-subject-pick]").forEach(function (pick) {
      var form = pick.form;
      var subject = form && form.elements.subject;
      var category = form && form.elements.category;
      if (!subject) return;
      pick.addEventListener("change", function () {
        var option = pick.options[pick.selectedIndex];
        if (!option || !option.value) return;
        subject.value = option.textContent.trim();
        var group = option.parentElement;
        if (category && group && group.getAttribute("data-category")) {
          category.value = group.getAttribute("data-category");
        }
      });
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

      function currentText() {
        return names.map(function (name) {
          var field = form.elements[name];
          return field ? field.value : "";
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
          if (field) data.append(name, field.value);
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
  });
})();

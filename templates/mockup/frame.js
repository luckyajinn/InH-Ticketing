/* Mockup only: runs first in every screen of mockups/ui-mockup.html.
   Links and forms go to the mockup around the page, never to a server. */
(function () {
  "use strict";

  function tell(message) {
    message.mockup = true;
    window.parent.postMessage(message, "*");
  }

  function formMessage(form, submitter) {
    var method = (form.getAttribute("method") || "get").toLowerCase();
    var query = "";
    if (method === "get") {
      var data;
      try { data = new FormData(form, submitter || undefined); } catch (e) { data = new FormData(form); }
      query = new URLSearchParams(data).toString();
    }
    return { type: "submit", method: method, action: form.getAttribute("action") || "", query: query };
  }

  // Put a form back as it was: the app shows "Sending..." until the next page loads.
  function settle(form) {
    form.removeAttribute("aria-busy");
    form.classList.remove("is-saving");
    form.querySelectorAll(".is-sending").forEach(function (button) { button.classList.remove("is-sending"); });
  }

  try {
    // Drafts are kept per page address, and every screen here has the same one.
    Object.keys(window.localStorage).forEach(function (key) {
      if (key.indexOf("inh-draft:") === 0) window.localStorage.removeItem(key);
    });
    // The admin site keeps its own theme choice; follow the mockup's.
    window.localStorage.setItem("theme", document.documentElement.getAttribute("data-theme") || "auto");
  } catch (e) { /* storage blocked: nothing to tidy */ }

  // The "this might include a password" check asks the server. Answer here
  // with a simple version of it, so the warning can still be tried.
  var FIELDS = { subject: "the subject", description: "the description", body: "your message" };
  var LABELLED = /\b(?:password|passwd|passcode|pwd|pin)\b(?:\s*(?:is|was|:|=))?\s*["'“]?([^\s"'”]{4,})/i;
  window.fetch = function (url, options) {
    var body = options && options.body;
    if (String(url).indexOf("check-text") !== -1 && body instanceof FormData) {
      var hints = [];
      Object.keys(FIELDS).forEach(function (name) {
        var match = LABELLED.exec(body.get(name) || "");
        if (!match) return;
        var secret = match[1];
        var lead = match[0].slice(0, match[0].length - secret.length);
        hints.push("In " + FIELDS[name] + ": …" + lead + secret.charAt(0) + new Array(secret.length).join("•"));
      });
      return Promise.resolve(new Response(JSON.stringify({ found: hints.length > 0, hints: hints }), {
        headers: { "Content-Type": "application/json" }
      }));
    }
    return Promise.reject(new Error("Nothing is sent from the mockup."));
  };

  HTMLFormElement.prototype.submit = function () {
    settle(this);
    tell(formMessage(this));
  };

  document.addEventListener("click", function (event) {
    var target = event.target;
    if (!target.closest) return;
    var link = target.closest("a[href]");
    if (link) {
      var href = link.getAttribute("href");
      if (href.charAt(0) === "#") return; // the skip link and other places on the page
      event.preventDefault();
      tell({ type: "go", href: href });
      return;
    }
    // Whole queue rows are clickable in the app too.
    var row = target.closest("tr[data-href]");
    if (row && !target.closest("button, input, select, label, textarea")) {
      event.stopPropagation();
      tell({ type: "go", href: row.getAttribute("data-href") });
    }
  }, true);

  // Listening as the event bubbles, so the page's own checks (the password
  // warning) run first. Only a form that would really be sent gets here.
  document.addEventListener("submit", function (event) {
    if (event.defaultPrevented) return;
    event.preventDefault();
    settle(event.target);
    tell(formMessage(event.target, event.submitter));
  });
})();

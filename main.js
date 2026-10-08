/* PDF to EPUB — landing page behaviour.
 *
 * Three jobs, no dependencies: a header that earns its border once the page
 * has scrolled, a mobile menu that is genuinely closed when it looks closed,
 * and smooth anchor scrolling that lands below the sticky header instead of
 * underneath it.
 *
 * Everything degrades: with JavaScript off the header is still sticky, the
 * nav links still work as anchors, and the menu markup is a plain list.
 */
(function () {
  "use strict";

  var header = document.getElementById("header");
  var nav = document.getElementById("nav");
  var toggle = document.getElementById("nav-toggle");

  /* --- header: border only when there is something above it ----------- */

  if (header) {
    var lastScrolled = null;
    var onScroll = function () {
      var scrolled = window.scrollY > 4;
      // Writing the attribute on every frame would invalidate style
      // constantly; only a change is worth touching the DOM for.
      if (scrolled !== lastScrolled) {
        header.dataset.scrolled = String(scrolled);
        lastScrolled = scrolled;
      }
    };
    // `passive` so scrolling is never waiting on this handler.
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
  }

  /* --- mobile menu ----------------------------------------------------- */

  var setMenu = function (open) {
    if (!nav || !toggle) return;
    nav.dataset.open = String(open);
    toggle.setAttribute("aria-expanded", String(open));
  };

  var isMenuOpen = function () {
    return Boolean(nav && nav.dataset.open === "true");
  };

  if (toggle && nav) {
    toggle.addEventListener("click", function () {
      setMenu(!isMenuOpen());
    });

    // A tap on a link navigates; leaving the sheet over the destination is
    // the most common way a menu like this feels broken.
    nav.addEventListener("click", function (event) {
      if (event.target.closest("a")) setMenu(false);
    });

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && isMenuOpen()) {
        setMenu(false);
        toggle.focus();
      }
    });

    // Tapping the page behind the sheet should shut it.
    document.addEventListener("click", function (event) {
      if (!isMenuOpen()) return;
      if (nav.contains(event.target) || toggle.contains(event.target)) return;
      setMenu(false);
    });

    // Crossing into the desktop layout leaves the sheet's state stale: the
    // CSS stops showing it, but `aria-expanded` would still claim it is open.
    var wide = window.matchMedia("(min-width: 52rem)");
    var syncToLayout = function (event) {
      if (event.matches) setMenu(false);
    };
    if (typeof wide.addEventListener === "function") {
      wide.addEventListener("change", syncToLayout);
    } else if (typeof wide.addListener === "function") {
      wide.addListener(syncToLayout); // Safari < 14
    }

    setMenu(false);
  }

  /* --- anchor scrolling that clears the sticky header ------------------ */

  var headerOffset = function () {
    return header ? header.getBoundingClientRect().height + 12 : 0;
  };

  var prefersReducedMotion = window.matchMedia(
    "(prefers-reduced-motion: reduce)"
  ).matches;

  document.addEventListener("click", function (event) {
    var link = event.target.closest('a[href^="#"]');
    if (!link) return;

    var id = link.getAttribute("href");
    if (!id || id === "#") return;

    var target = document.querySelector(id);
    if (!target) return;

    event.preventDefault();

    var top =
      target.getBoundingClientRect().top + window.scrollY - headerOffset();

    window.scrollTo({
      top: top < 0 ? 0 : top,
      behavior: prefersReducedMotion ? "auto" : "smooth"
    });

    // Scrolling alone moves the viewport but not the keyboard, so a keyboard
    // user would carry on tabbing from the top of the page. `tabindex="-1"`
    // lets a section take focus without becoming a tab stop of its own.
    if (!target.hasAttribute("tabindex")) {
      target.setAttribute("tabindex", "-1");
    }
    target.focus({ preventScroll: true });

    // Keep the address bar in step so the position survives a reload or a
    // copied link, without adding a history entry per click.
    if (window.history && window.history.replaceState) {
      window.history.replaceState(null, "", id);
    }
  });

  /* --- footer year ----------------------------------------------------- */

  var year = document.getElementById("year");
  if (year) year.textContent = String(new Date().getFullYear());
})();

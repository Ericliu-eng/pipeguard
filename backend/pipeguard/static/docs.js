// The API reference's overview: health in the header, Copy, and Authorize.
(() => {
  const health = document.getElementById("pg-health");
  fetch("/health", { headers: { Accept: "application/json" } })
    .then((response) => {
      health.classList.add(response.ok ? "ok" : "bad");
      health.lastChild.textContent = response.ok ? "API healthy" : "API degraded";
    })
    .catch(() => {
      health.classList.add("bad");
      health.lastChild.textContent = "API unreachable";
    });

  document.querySelectorAll("[data-copy]").forEach((button) => {
    button.addEventListener("click", async () => {
      const text = document.getElementById(button.dataset.copy).textContent;
      try {
        await navigator.clipboard.writeText(text);
        button.textContent = "Copied";
      } catch {
        button.textContent = "Select and copy";
      }
      setTimeout(() => { button.textContent = "Copy"; }, 1600);
    });
  });

  // Swagger UI owns the authorization dialog; the header button opens it.
  document.getElementById("pg-authorize").addEventListener("click", () => {
    document.querySelector(".swagger-ui .auth-wrapper .btn.authorize")?.click();
  });
})();

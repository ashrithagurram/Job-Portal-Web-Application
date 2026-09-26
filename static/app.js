document.addEventListener("submit", (event) => {
  const message = event.target.dataset.confirm;
  if (message && !window.confirm(message)) {
    event.preventDefault();
  }
});

document.querySelectorAll('input[name="role"]').forEach((input) => {
  input.addEventListener("change", () => {
    const companyField = document.querySelector(".company-field");
    if (!companyField) return;
    const isEmployer = document.querySelector('input[name="role"]:checked')?.value === "employer";
    companyField.classList.toggle("company-field-visible", isEmployer);
    companyField.querySelector("input").required = isEmployer;
  });
});
document.addEventListener("DOMContentLoaded", () => {
  const toggle = document.getElementById("menuToggle");
  const nav = document.getElementById("mainNav");
  if (toggle && nav) toggle.addEventListener("click", () => nav.classList.toggle("open"));

  document.querySelectorAll(".flash").forEach((message) => {
    setTimeout(() => {
      message.style.opacity = "0";
      message.style.transform = "translateY(-6px)";
    }, 5000);
  });
});
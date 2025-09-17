async function loadComponent(id, file) {
  const res = await fetch(file);
  const html = await res.text();
  document.getElementById(id).innerHTML = html;
}

document.addEventListener("DOMContentLoaded", () => {
  loadComponent("header", "/static/partials/header.html"); 
  loadComponent("footer", "/static/partials/footer.html");
});

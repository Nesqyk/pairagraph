// Progressive enhancement only; all persistence and authorization live on the server.
document.querySelectorAll('[data-learner-form]').forEach((form) => {
  const role = form.querySelector('[data-role]');
  const goal = form.querySelector('[data-goal]');
  const options = Array.from(goal.options).map((option) => ({value: option.value, role: option.dataset.role}));
  function updateGoals() {
    goal.replaceChildren(...options.filter((option) => option.role === role.value).map((option) => new Option(option.value, option.value)));
  }
  role.addEventListener('change', updateGoals);
  updateGoals();
});

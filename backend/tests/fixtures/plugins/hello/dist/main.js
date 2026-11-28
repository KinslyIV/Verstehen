const HAND =
  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 11V6a2 2 0 0 0-4 0v5"/><path d="M14 10V4a2 2 0 0 0-4 0v6"/><path d="M10 10.5V6a2 2 0 0 0-4 0v8"/><path d="M18 8a2 2 0 1 1 4 0v6a8 8 0 0 1-8 8h-2c-2.8 0-4.5-.9-5.9-2.4L3.4 16a2 2 0 0 1 3.2-2.4L8 15"/></svg>';

export function activate(ctx) {
  ctx.registerView({
    id: 'main',
    name: 'Hello',
    mount(container, signal) {
      const root = document.createElement('div');
      root.className = 'hello-view';
      root.dataset.testid = 'hello-view';
      root.innerHTML =
        '<h2 data-testid="hello-heading">Say hello</h2>' +
        '<div class="hello-row"><input class="hello-input" aria-label="Name" placeholder="Name" />' +
        '<span data-slot="greet"></span></div>' +
        '<div class="hello-row" data-slot="count"></div>' +
        '<div data-slot="answer" data-testid="hello-answer"></div>';
      container.append(root);
      const input = root.querySelector('input');
      const answer = root.querySelector('[data-slot="answer"]');
      const options = { signal };
      const badge = ctx.ui.mountBadge(
        root.querySelector('[data-slot="count"]'),
        { text: 'Lookups: 0' },
        options,
      );
      const markdown = ctx.ui.mountMarkdown(answer, { text: 'Nothing greeted yet.' }, options);
      async function refreshCount() {
        const lookups = await ctx.backend.lookups_so_far();
        badge.update({ text: `Lookups: ${lookups.length}` });
      }
      ctx.ui.mountButton(
        root.querySelector('[data-slot="greet"]'),
        {
          label: 'Greet',
          variant: 'secondary',
          async onClick() {
            markdown.update({ text: `**${await ctx.backend.greet(input.value)}**` });
            await refreshCount();
          },
        },
        options,
      );
      void refreshCount();
    },
  });

  ctx.registerAction({
    id: 'open-view',
    name: 'Hello',
    icon: HAND,
    run: () => ctx.app.openView('main'),
  });
  ctx.placeAction({ id: 'sidebar-open', actionId: 'open-view', location: 'sidebar' });

  ctx.registerAction({
    id: 'greet-session',
    name: 'Greet this session',
    icon: HAND,
    async run(context) {
      const message = await ctx.backend.greet(`session ${context.sessionId.slice(0, 4)}`);
      ctx.ui.openDialog(
        {
          title: 'Hello',
          content(container) {
            const text = document.createElement('p');
            text.dataset.testid = 'hello-dialog-message';
            text.textContent = message;
            container.append(text);
          },
        },
        { signal: ctx.signal },
      );
    },
  });
  ctx.placeAction({
    id: 'top-greet',
    actionId: 'greet-session',
    location: 'top-bar',
    sessions: ['teaching', 'practice'],
  });

  const rows = (settings) => [
    {
      type: 'text',
      key: 'name',
      label: 'Name to greet',
      description: 'Used when the greeting box is empty.',
      value: settings.name,
      async onChange(value) {
        await ctx.backend.save_settings({ name: value });
      },
    },
    {
      type: 'toggle',
      key: 'loud',
      label: 'Loud greeting',
      value: settings.loud,
      async onChange(value) {
        await ctx.backend.save_settings({ loud: value });
      },
    },
  ];
  ctx.registerSettings({
    async mount(container, signal) {
      const settings = await ctx.backend.get_settings();
      ctx.ui.mountSettingsRows(container, { rows: rows(settings) }, { signal });
    },
  });
}

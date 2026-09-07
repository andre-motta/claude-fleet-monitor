export default function fixtureExtension(pi) {
  pi.registerCommand("fleet-fixture-wait", {
    description: "Open a synthetic input prompt",
    handler: async (_args, ctx) => {
      await ctx.ui.input("Synthetic Fleet validation input");
    },
  });
  pi.registerCommand("fleet-fixture-reload", {
    description: "Reload extensions for Fleet validation",
    handler: async (_args, ctx) => {
      await ctx.reload();
    },
  });
  pi.registerCommand("fleet-fixture-exit", {
    description: "Exit the synthetic Fleet validation session",
    handler: async (_args, ctx) => {
      ctx.shutdown();
    },
  });
}

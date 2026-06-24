// Background used across the whole site — softened off-white → soft lavender
// (gentle, easy on the eyes).
export const Background = () => {
  return (
    <div className="absolute inset-0 -z-10 h-full w-full bg-[#f7f6fb] [background:radial-gradient(125%_125%_at_50%_10%,#f7f6fb_45%,#cdc4f2_100%)]" />
  );
};

// Grid variant (kept for reference / alternate use).
export const GridBackground = () => {
  return (
    <div className="absolute inset-0 -z-10 h-full w-full bg-white bg-[linear-gradient(to_right,#f0f0f0_1px,transparent_1px),linear-gradient(to_bottom,#f0f0f0_1px,transparent_1px)] bg-[size:6rem_4rem]">
      <div className="absolute bottom-0 left-0 right-0 top-0 bg-[radial-gradient(circle_800px_at_100%_200px,#d5c5ff,transparent)]" />
    </div>
  );
};

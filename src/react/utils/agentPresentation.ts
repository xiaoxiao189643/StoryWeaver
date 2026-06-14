export function getAgentAvatar(name = "", _id = "") {
  if (name.includes("玩家") || name.includes("player")) return "你";
  if (name.includes("导演") || name.includes("系统")) return "导";
  // 返回名字的第一个字（姓氏）
  return name.charAt(0) || "?";
}

export function getAgentRole(name = "", id = "") {
  const key = `${name} ${id}`;
  if (key.includes("林") || key.includes("detective")) return "侦探";
  if (key.includes("陈") || key.includes("butler")) return "管家";
  if (key.includes("苏") || key.includes("hostess")) return "女主人";
  if (key.includes("马克") || key.includes("guest")) return "神秘访客";
  if (key.includes("玩家") || key.includes("player")) return "玩家";
  return "角色";
}

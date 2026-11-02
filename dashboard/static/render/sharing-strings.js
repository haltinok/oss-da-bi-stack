// The words of folders, sharing and the trash on the dashboards list (/d/), English and Turkish.
const EN = {
  folder: "Folder", noFolder: "No folder", newFolder: "New folder", folderName: "Folder name", create: "Create", rename: "Rename", delete: "Delete", cancel: "Cancel", save: "Save", close: "Close",
  share: "Share…", shareTitle: (what) => `Share: ${what}`, shareWith: "Shared with", sharePerson: "A person", shareGroup: "A group", shareName: "Username or group name", shareView: "Can view", shareEdit: "Can edit",
  shareAdd: "Add", shareNobody: "Nobody yet: only you (and admins) can open it, unless it is shared with roles or everyone.", shareHint: "Type the person's username, or the group's name, exactly as in the admin console.",
  moveTo: "Folder", owner: "Owner", ownerHint: "Handing it over makes the other person its owner; you lose the right to change how it is shared.", ownerChange: "New owner (username)",
  folderShare: "Share this folder", folderShared: "What is in a shared folder is shared with the same people.", folderDeleteConfirm: (n) => `Delete the folder “${n}”? What is in it stays, outside any folder.`,
  trash: (n) => `Trash (${n})`, trashHint: "Deleted dashboards are kept for 30 days.", restore: "Restore", deleteForever: "Delete for good", deleteForeverConfirm: "Delete it for good? This cannot be undone.", trashEmpty: "The trash is empty.",
  inFolder: (n) => `in ${n}`, sharedBadge: "shared with you", failed: "Could not do that:", remove: "Remove",
};
const TR = {
  folder: "Klasör", noFolder: "Klasörsüz", newFolder: "Yeni klasör", folderName: "Klasör adı", create: "Oluştur", rename: "Yeniden adlandır", delete: "Sil", cancel: "Vazgeç", save: "Kaydet", close: "Kapat",
  share: "Paylaş…", shareTitle: (what) => `Paylaş: ${what}`, shareWith: "Paylaşılanlar", sharePerson: "Bir kişi", shareGroup: "Bir grup", shareName: "Kullanıcı adı ya da grup adı", shareView: "Görebilir", shareEdit: "Değiştirebilir",
  shareAdd: "Ekle", shareNobody: "Henüz kimse yok: rollerle ya da herkesle paylaşılmadıkça yalnızca siz (ve yöneticiler) açabilir.", shareHint: "Kişinin kullanıcı adını ya da grubun adını yönetim sayfasındaki gibi yazın.",
  moveTo: "Klasör", owner: "Sahibi", ownerHint: "Devretmek, diğer kişiyi sahibi yapar; nasıl paylaşıldığını değiştirme hakkınızı kaybedersiniz.", ownerChange: "Yeni sahip (kullanıcı adı)",
  folderShare: "Bu klasörü paylaş", folderShared: "Paylaşılan bir klasördeki her şey aynı kişilerle paylaşılır.", folderDeleteConfirm: (n) => `“${n}” klasörü silinsin mi? İçindekiler klasörsüz olarak kalır.`,
  trash: (n) => `Çöp kutusu (${n})`, trashHint: "Silinen panolar 30 gün saklanır.", restore: "Geri al", deleteForever: "Kalıcı sil", deleteForeverConfirm: "Kalıcı olarak silinsin mi? Bu geri alınamaz.", trashEmpty: "Çöp kutusu boş.",
  inFolder: (n) => `${n} klasöründe`, sharedBadge: "sizinle paylaşıldı", failed: "Yapılamadı:", remove: "Çıkar",
};
export const sharingStrings = (locale = "en") => ({ ...EN, ...(String(locale).startsWith("tr") ? TR : {}) });

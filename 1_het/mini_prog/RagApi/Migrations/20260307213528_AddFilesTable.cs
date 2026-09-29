using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace RagApi.Migrations
{
    /// <inheritdoc />
    public partial class AddFilesTable : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropForeignKey(
                name: "FK_File_Project_DbProjectID",
                table: "File");

            migrationBuilder.DropIndex(
                name: "IX_File_DbProjectID",
                table: "File");

            migrationBuilder.DropColumn(
                name: "DbProjectID",
                table: "File");

            migrationBuilder.RenameColumn(
                name: "path",
                table: "File",
                newName: "StoragePath");

            migrationBuilder.AddColumn<string>(
                name: "ContentType",
                table: "File",
                type: "nvarchar(max)",
                nullable: false,
                defaultValue: "");

            migrationBuilder.AddColumn<string>(
                name: "Extension",
                table: "File",
                type: "nvarchar(max)",
                nullable: false,
                defaultValue: "");

            migrationBuilder.AddColumn<string>(
                name: "RelativePath",
                table: "File",
                type: "nvarchar(max)",
                nullable: false,
                defaultValue: "");

            migrationBuilder.AddColumn<long>(
                name: "Size",
                table: "File",
                type: "bigint",
                nullable: false,
                defaultValue: 0L);

            migrationBuilder.CreateIndex(
                name: "IX_File_ProjectID",
                table: "File",
                column: "ProjectID");

            migrationBuilder.AddForeignKey(
                name: "FK_File_Project_ProjectID",
                table: "File",
                column: "ProjectID",
                principalTable: "Project",
                principalColumn: "ID",
                onDelete: ReferentialAction.Cascade);
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropForeignKey(
                name: "FK_File_Project_ProjectID",
                table: "File");

            migrationBuilder.DropIndex(
                name: "IX_File_ProjectID",
                table: "File");

            migrationBuilder.DropColumn(
                name: "ContentType",
                table: "File");

            migrationBuilder.DropColumn(
                name: "Extension",
                table: "File");

            migrationBuilder.DropColumn(
                name: "RelativePath",
                table: "File");

            migrationBuilder.DropColumn(
                name: "Size",
                table: "File");

            migrationBuilder.RenameColumn(
                name: "StoragePath",
                table: "File",
                newName: "path");

            migrationBuilder.AddColumn<int>(
                name: "DbProjectID",
                table: "File",
                type: "int",
                nullable: true);

            migrationBuilder.CreateIndex(
                name: "IX_File_DbProjectID",
                table: "File",
                column: "DbProjectID");

            migrationBuilder.AddForeignKey(
                name: "FK_File_Project_DbProjectID",
                table: "File",
                column: "DbProjectID",
                principalTable: "Project",
                principalColumn: "ID");
        }
    }
}

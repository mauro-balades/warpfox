use anyhow::Context;
use std::path::PathBuf;

pub async fn build_firefox(source_dir: &PathBuf) -> Result<(), anyhow::Error> {
  let status = std::process::Command::new("./mach")
      .arg("build")
      .arg("-j8")
      .current_dir(source_dir)
      .status()
      .context("Failed to execute build command")?;
  if !status.success() {
      return Err(anyhow::anyhow!(
          "Build command failed with status: {}",
          status
      ));
  }
  log::info!("Build completed successfully");
  Ok(())
}

pub async fn bootstrap_firefox(source_dir: &PathBuf) -> Result<(), anyhow::Error> {
  let status = std::process::Command::new("./mach")
      .arg("bootstrap")
      .arg("--no-interactive")
      .arg("--application-choice=browser")
  if !status.success() {
      return Err(anyhow::anyhow!(
          "Build command failed with status: {}",
          status
      ));
  }
  log::info!("Bootstrap completed successfully");
  Ok(())
}
